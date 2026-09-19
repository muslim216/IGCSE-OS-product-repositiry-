"""Read and set an organization's mistake categories for a subject.

The five-member `MistakeCategory` enum said every tutor of every subject sorts
mistakes the same way (see `models/readiness_v2.py`). This is the control that
replaces it: a per-(organization, subject) list the tutor owns, with a
published starting point offered on read and written only on save
(`services/mistake_categories.py`).

Tutor-only, like `api/marking_rules.py` — a student sees which categories their
own mistakes were tagged with (a later PR), not the editor. The organization
comes from the authenticated tutor and never from the path (`PROD-4`/`SEC-7`);
the role gate is a signature dependency (`SEC-11`/`BE-17`); an unknown or
other-org subject is a 404, never a 403 (`API-7`/`SEC-9`).
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, TutorUser, owned_subject
from app.schemas.mistake_categories import (
    MistakeCategoriesIn,
    MistakeCategoriesOut,
    MistakeCategoryItem,
)
from app.services.mistake_categories import defaults_for_subject, list_categories, save_categories

router = APIRouter(prefix="/subjects", tags=["mistake-categories"])


def _items(rows) -> list[MistakeCategoryItem]:
    return [
        MistakeCategoryItem(id=row.id, name=row.name, description=row.description) for row in rows
    ]


@router.get("/{subject_id}/mistake-categories", response_model=MistakeCategoriesOut)
async def read_mistake_categories(
    subject_id: int, db: DbSession, user: TutorUser
) -> MistakeCategoriesOut:
    """This organization's mistake categories for the subject, and whether
    they are set. `source` travels with the list for the same reason it does
    on grade boundaries: the tutor's own list and an unconfirmed starting
    point are different facts and must not render alike (`PROD-8`)."""
    subject = await owned_subject(db, subject_id, user)
    categories = await list_categories(db, user.organization_id, subject.id)
    if categories:
        return MistakeCategoriesOut(
            subject_id=subject.id,
            subject_name=subject.name,
            source="organization",
            categories=_items(categories),
        )
    return MistakeCategoriesOut(
        subject_id=subject.id,
        subject_name=subject.name,
        source="none",
        categories=[
            MistakeCategoryItem(id=None, name=item["name"], description=item["description"])
            for item in defaults_for_subject()
        ],
    )


@router.put("/{subject_id}/mistake-categories", response_model=MistakeCategoriesOut)
async def write_mistake_categories(
    subject_id: int, body: MistakeCategoriesIn, db: DbSession, user: TutorUser
) -> MistakeCategoriesOut:
    """Diff this organization's categories for a subject against the payload.

    Diffs rather than replaces — a category a `Mistake` row points at is
    archived, never deleted, when the tutor drops it from the list
    (`services/mistake_categories.py`).
    """
    subject = await owned_subject(db, subject_id, user)
    try:
        saved = await save_categories(
            db,
            user.organization_id,
            subject.id,
            [item.model_dump() for item in body.categories],
        )
    except ValueError as exc:
        # A payload id that is not one of this (organization, subject)'s own
        # rows — never someone else's row updated because the id happened to
        # exist (SEC-7); indistinguishable to the caller from one that never
        # existed (API-7, SEC-9).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mistake category not found") from exc
    except IntegrityError as exc:
        # Two tutors in one organization saving the same subject at once. The
        # second save diffed against a list that had already moved, so a name
        # it believed was free is taken by the time it flushes.
        #
        # The payload is the whole list, so the later save wins — the same
        # contract `set_org_boundaries` has. Archiving rather than deleting is
        # what makes that survivable: a category the other tutor added and this
        # save did not know about is archived, not destroyed, and re-adding the
        # name brings back the same row with everything tagged against it. What
        # must not happen is a 500 for an edit that is legal and merely late,
        # with no way to tell the tutor which it was (cubic).
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "These categories changed while you were editing. Reload the list and try again.",
        ) from exc
    await db.commit()
    return MistakeCategoriesOut(
        subject_id=subject.id,
        subject_name=subject.name,
        source="organization",
        categories=_items(saved),
    )
