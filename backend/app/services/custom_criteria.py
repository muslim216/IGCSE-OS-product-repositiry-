"""Tutor-defined criteria and the hand-entered scores on them (task 5.4b).

**Beside readiness, never in it.** Nothing in the readiness engine or its
synthesis prompt imports this module or reads its tables, and nothing here has
a weight: a tutor's 0-100 has no evidence behind it (`PROD-1`).

**Unscored is absent.** No score row means no score, returned as `None` and
never as 0 (`PROD-2`).

**Every edit is audited in the same transaction as the edit** — set, change and
clear each write one `CustomCriterionScoreAudit` row; an edit that changes
nothing writes none (`PROD-7`). Nothing here commits: the caller does, so the
score and its audit row land together or not at all.

Scoping errors are exceptions the router maps to status codes, because a
service must not import the web layer (`BE-1`).
"""

from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CustomCriterion,
    CustomCriterionScore,
    CustomCriterionScoreAudit,
    StudentSubject,
    Subject,
)
from app.models.base import utcnow


class CriterionNotFound(LookupError):
    """Missing, or another organization's — deliberately indistinguishable (`API-7`)."""


class CriterionConflict(ValueError):
    """The criterion exists but cannot be scored for this student right now."""


async def list_criteria(
    session: AsyncSession, organization_id: int, *, include_archived: bool = False
) -> list[CustomCriterion]:
    query = select(CustomCriterion).where(CustomCriterion.organization_id == organization_id)
    if not include_archived:
        query = query.where(CustomCriterion.archived_at.is_(None))
    return list((await session.scalars(query.order_by(CustomCriterion.id))).all())


async def create_criterion(
    session: AsyncSession,
    organization_id: int,
    created_by_id: int,
    *,
    name: str,
    description: str | None,
    subject_id: int | None,
) -> CustomCriterion:
    """The caller has already proved `subject_id` belongs to this organization."""
    criterion = CustomCriterion(
        organization_id=organization_id,
        subject_id=subject_id,
        name=name,
        description=description,
        created_by_id=created_by_id,
    )
    session.add(criterion)
    await session.flush()
    return criterion


async def owned_criterion(
    session: AsyncSession, organization_id: int, criterion_id: int
) -> CustomCriterion:
    criterion = await session.get(CustomCriterion, criterion_id)
    if criterion is None or criterion.organization_id != organization_id:
        raise CriterionNotFound
    return criterion


def update_criterion(criterion: CustomCriterion, changes: dict) -> None:
    """Apply a PATCH. `subject_id` is not accepted: scores were given against
    the scope the criterion was created with."""
    if "name" in changes:
        criterion.name = changes["name"]
    if "description" in changes:
        criterion.description = changes["description"]
    if "archived" in changes:
        # Re-archiving keeps the original timestamp — it records when the
        # criterion stopped being used, not when someone last pressed the button.
        if not changes["archived"]:
            criterion.archived_at = None
        elif criterion.archived_at is None:
            criterion.archived_at = utcnow()


def _enrolled_subjects(student_id: int):
    return select(StudentSubject.subject_id).where(StudentSubject.student_id == student_id)


async def criteria_for_student(
    session: AsyncSession, organization_id: int, student_id: int
) -> list[tuple[CustomCriterion, CustomCriterionScore | None]]:
    """Every live criterion that applies to this student, with their score or None.

    Applies = not archived, and either for every subject or for one the
    student is enrolled in. An archived criterion's score survives but is not
    shown — unarchiving brings it back as it was.
    """
    rows = await session.execute(
        select(CustomCriterion, CustomCriterionScore)
        .outerjoin(
            CustomCriterionScore,
            (CustomCriterionScore.criterion_id == CustomCriterion.id)
            & (CustomCriterionScore.student_id == student_id),
        )
        .where(
            CustomCriterion.organization_id == organization_id,
            CustomCriterion.archived_at.is_(None),
            or_(
                CustomCriterion.subject_id.is_(None),
                CustomCriterion.subject_id.in_(_enrolled_subjects(student_id)),
            ),
        )
        .order_by(CustomCriterion.id)
    )
    return [(criterion, score) for criterion, score in rows.all()]


async def subject_names(
    session: AsyncSession, criteria: Iterable[CustomCriterion], organization_id: int
) -> dict[int, str]:
    """The name of each subject these criteria are scoped to, by subject id.

    Two subject-specific criteria may share a name — "Effort" for Chemistry and
    for Physics — and are the same line twice unless each says which it is. An
    account-wide criterion has no subject and so no entry.

    Filtered by organization as well as by id: the criteria passed in should
    already be one organization's, and this is what keeps another tenant's
    subject name off the page if a caller ever gets that wrong (`SEC-7`).
    """
    ids = {c.subject_id for c in criteria if c.subject_id is not None}
    if not ids:
        return {}
    rows = await session.execute(
        select(Subject.id, Subject.name).where(
            Subject.id.in_(ids), Subject.organization_id == organization_id
        )
    )
    return dict(tuple(row) for row in rows.all())


async def _scorable(
    session: AsyncSession, organization_id: int, student_id: int, criterion_id: int
) -> CustomCriterion:
    criterion = await owned_criterion(session, organization_id, criterion_id)
    if criterion.archived_at is not None:
        raise CriterionConflict("This criterion is archived. Unarchive it to change scores.")
    if criterion.subject_id is not None:
        enrolled = await session.scalar(
            _enrolled_subjects(student_id).where(StudentSubject.subject_id == criterion.subject_id)
        )
        if enrolled is None:
            raise CriterionConflict(
                "This criterion is for a subject the student is not enrolled in. "
                "Enroll them in the subject first."
            )
    return criterion


async def _current_score(
    session: AsyncSession, student_id: int, criterion_id: int
) -> CustomCriterionScore | None:
    # Locked on Postgres so two tutors editing one score at once serialise and
    # each audit row's `old_score` is what was really there. SQLite ignores it.
    return await session.scalar(
        select(CustomCriterionScore)
        .where(
            CustomCriterionScore.student_id == student_id,
            CustomCriterionScore.criterion_id == criterion_id,
        )
        .with_for_update()
    )


def _audit(
    session: AsyncSession,
    criterion: CustomCriterion,
    student_id: int,
    old: int | None,
    new: int | None,
    changed_by_id: int,
) -> None:
    session.add(
        CustomCriterionScoreAudit(
            organization_id=criterion.organization_id,
            student_id=student_id,
            criterion_id=criterion.id,
            old_score=old,
            new_score=new,
            changed_by_id=changed_by_id,
        )
    )


async def set_score(
    session: AsyncSession,
    organization_id: int,
    student_id: int,
    criterion_id: int,
    score: int,
    changed_by_id: int,
) -> tuple[CustomCriterion, CustomCriterionScore]:
    """Upsert the score and audit the change.

    Two first-time scores racing both see no row and both insert; the unique
    constraint rejects the second at flush with an IntegrityError, which is
    left to propagate — the caller rolls back and reports a conflict rather
    than this guessing which tutor meant it.
    """
    criterion = await _scorable(session, organization_id, student_id, criterion_id)
    row = await _current_score(session, student_id, criterion_id)
    if row is not None and row.score == score:
        return criterion, row
    old = None if row is None else row.score
    if row is None:
        row = CustomCriterionScore(
            organization_id=organization_id, student_id=student_id, criterion_id=criterion_id
        )
        session.add(row)
    row.score = score
    row.updated_at = utcnow()
    row.updated_by_id = changed_by_id
    _audit(session, criterion, student_id, old, score, changed_by_id)
    await session.flush()
    return criterion, row


async def clear_score(
    session: AsyncSession,
    organization_id: int,
    student_id: int,
    criterion_id: int,
    changed_by_id: int,
) -> None:
    """Delete the score and audit it as cleared. Clearing nothing is a no-op."""
    criterion = await _scorable(session, organization_id, student_id, criterion_id)
    row = await _current_score(session, student_id, criterion_id)
    if row is None:
        return
    _audit(session, criterion, student_id, row.score, None, changed_by_id)
    await session.delete(row)
    await session.flush()
