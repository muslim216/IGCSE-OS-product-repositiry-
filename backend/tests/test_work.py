"""Every piece of work has a parent row, and the parent agrees with it.

`assessable_work.organization_id` is a *copy* of the child's tenant, written by
`create_work`. The whole point of the table is that the cross-kind queries can
trust that one column instead of ORing three, so a parent that disagrees with
its child would hide a tutor's work from the review queue or show it to the
wrong tenant. These tests are what stop a second creation path appearing.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import async_session
from app.models import (
    AssessableWork,
    Assignment,
    AssignmentStatus,
    Group,
    Submission,
    User,
    UserRole,
    WorkKind,
)
from app.services.work import create_work, parent_of
from tests.factories import make_subject


async def _tutor_and_group(session, *, email: str) -> Group:
    """A real `User` row, not `tutor_id=1`. The suite runs on SQLite with
    foreign keys off, so a dangling id passes here and fails on Postgres —
    `RISK-3`, the failure that has actually happened in this repository
    (cubic, on the D2 PR)."""
    subject = await make_subject(session)
    tutor = User(
        organization_id=subject.organization_id,
        email=email,
        name="Work Tutor",
        password_hash="x",
        role=UserRole.tutor,
    )
    session.add(tutor)
    await session.flush()
    group = Group(
        organization_id=subject.organization_id,
        tutor_id=tutor.id,
        subject_id=subject.id,
        name="Y11",
    )
    session.add(group)
    await session.flush()
    return group


async def test_create_work_copies_the_tenant_and_the_subject() -> None:
    async with async_session() as session:
        subject = await make_subject(session)
        work = await create_work(
            session,
            kind=WorkKind.homework,
            organization_id=subject.organization_id,
            subject_id=subject.id,
            title="HW1",
        )
        await session.commit()

        stored = await session.get(AssessableWork, work.id)
        assert stored is not None
        assert stored.organization_id == subject.organization_id
        assert stored.subject_id == subject.id
        assert stored.kind is WorkKind.homework
        assert stored.title == "HW1"


async def test_a_parent_may_have_no_title_yet() -> None:
    """A past paper is unnamed until extraction reads the document. `PROD-2`
    forbids inventing a title, so the parent carries the absence too."""
    async with async_session() as session:
        subject = await make_subject(session)
        work = await create_work(
            session,
            kind=WorkKind.past_paper,
            organization_id=subject.organization_id,
            subject_id=subject.id,
            title=None,
        )
        await session.commit()
        assert (await session.get(AssessableWork, work.id)).title is None


async def test_a_piece_of_work_cannot_exist_without_a_parent() -> None:
    """The guarantee D2 buys: `work_id` is NOT NULL, so a create path that
    forgets the parent fails loudly here instead of writing a row the
    cross-kind queries cannot see."""
    async with async_session() as session:
        group = await _tutor_and_group(session, email="no-parent@example.com")

        session.add(Assignment(group_id=group.id, title="No parent"))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_two_pieces_of_work_cannot_share_one_parent() -> None:
    """`work_id` is unique per table, so a parent adopted twice is refused."""
    async with async_session() as session:
        group = await _tutor_and_group(session, email="shared-parent@example.com")
        work = await create_work(
            session,
            kind=WorkKind.homework,
            organization_id=group.organization_id,
            subject_id=group.subject_id,
            title="HW1",
        )
        session.add(Assignment(work_id=work.id, group_id=group.id, title="First"))
        await session.flush()

        session.add(Assignment(work_id=work.id, group_id=group.id, title="Second"))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_every_assignment_created_through_the_api_gets_a_parent(client, tutor, group) -> None:
    """The end-to-end guarantee, through the real endpoint rather than a model:
    no assignment reaches the database without a parent carrying its group's
    organization and subject."""
    created = await client.post(
        "/api/v1/assignments",
        json={"group_id": group["id"], "title": "HW1 — Waves"},
        headers=tutor["headers"],
    )
    assert created.status_code in (200, 201), created.text

    async with async_session() as session:
        assignment = await session.scalar(select(Assignment).order_by(Assignment.id.desc()))
        assert assignment is not None
        work = await session.get(AssessableWork, assignment.work_id)
        group_row = await session.get(Group, assignment.group_id)
        assert work is not None
        assert group_row is not None
        assert work.kind is WorkKind.homework
        assert work.organization_id == group_row.organization_id
        assert work.subject_id == group_row.subject_id
        assert work.title == "HW1 — Waves"


async def test_the_parent_is_found_through_work_id_not_a_stale_key(tutor, group):
    """Dispatch and loading must name the same piece of work.

    Both `work_id` and the old per-kind key are written until D6, and nothing
    at the database level forces them to agree. `kind_of` reads the parent, so
    if a loader read the old key instead, a contradictory row would be marked
    as one kind and have its marks written against another kind's paper. This
    pins both to `work_id`.
    """
    async with async_session() as session:
        group_row = await session.get(Group, group["id"])
        assert group_row is not None
        assignments = []
        for title in ("Real", "Stale"):
            work = await create_work(
                session,
                kind=WorkKind.homework,
                organization_id=group_row.organization_id,
                subject_id=group_row.subject_id,
                title=title,
            )
            assignment = Assignment(
                work_id=work.id,
                group_id=group["id"],
                title=title,
                status=AssignmentStatus.published,
            )
            session.add(assignment)
            await session.flush()
            assignments.append(assignment)
        real, stale = assignments

        submission = Submission(
            # Contradictory on purpose: the key says one assignment, the parent
            # says the other.
            assignment_id=stale.id,
            work_id=real.work_id,
            student_id=tutor["user"]["id"],
        )
        session.add(submission)
        await session.commit()

    async with async_session() as session:
        # Re-read the way every real caller does: a submission reaches
        # `parent_of` loaded from the database, with its parent row alongside.
        loaded = await session.scalar(select(Submission).where(Submission.id == submission.id))
        assert loaded is not None
        found = await parent_of(session, loaded)
    assert found is not None
    assert found.id == real.id, "the parent must come from work_id, not the old key"
