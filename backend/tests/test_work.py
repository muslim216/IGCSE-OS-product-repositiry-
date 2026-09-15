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
from app.models import AssessableWork, Assignment, Group, WorkKind
from app.services.work import create_work
from tests.factories import make_subject, org_id


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
        organization_id = await org_id(session)
        subject = await make_subject(session)
        group = Group(
            organization_id=organization_id,
            tutor_id=1,
            subject_id=subject.id,
            name="Y11",
        )
        session.add(group)
        await session.flush()

        session.add(Assignment(group_id=group.id, title="No parent"))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_two_pieces_of_work_cannot_share_one_parent() -> None:
    """`work_id` is unique per table, so a parent adopted twice is refused."""
    async with async_session() as session:
        organization_id = await org_id(session)
        subject = await make_subject(session)
        group = Group(
            organization_id=organization_id, tutor_id=1, subject_id=subject.id, name="Y11"
        )
        session.add(group)
        await session.flush()
        work = await create_work(
            session,
            kind=WorkKind.homework,
            organization_id=organization_id,
            subject_id=subject.id,
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
        assert work is not None and group_row is not None
        assert work.kind is WorkKind.homework
        assert work.organization_id == group_row.organization_id
        assert work.subject_id == group_row.subject_id
        assert work.title == "HW1 — Waves"
