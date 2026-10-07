"""Whether a student may hand a piece of work in, in one place per kind.

The student routes (`submit_work`, the past-paper log route, `sit_mock`) and a
tutor's redo (`services/attempt_redo`) must agree on this exactly: a redo that
deletes an attempt the student then cannot replace destroys marks for nothing.
Homework and past papers call these functions from both sides. A mock's student
route still goes through `_visible_mock(sitting=True)`, which carries the same
conditions plus its read-side variants; `mock_open_to` mirrors them and
`tests/test_attempt_redo_access.py` holds the two in step state by state.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assignment,
    AssignmentStatus,
    Group,
    GroupMember,
    Mock,
    MockStatus,
    PastPaper,
)
from app.services.submission_kind import HOMEWORK, MOCK, PAST_PAPER, SubmissionKind


async def enrolled_scope(db: AsyncSession, student_id: int) -> set[tuple[int, int]]:
    """The (organization_id, subject_id) pairs a student is actually taught in.

    Subjects are global — every organization shares the same five built-in
    syllabuses — so enrollment alone does not bound what a student may see.
    Scoping on the pair keeps one tutor's uploads inside that tutor's
    organization; matching on subject alone would show a student every past
    paper any tutor anywhere had uploaded for their subject.

    The pair comes from the groups the student is in rather than from
    `user.organization_id`, so a student who joined a second tutor's group with
    an invite (which does not move their organization) still sees that tutor's
    papers, and only that tutor's.
    """
    rows = (
        await db.execute(
            select(Group.organization_id, Group.subject_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            # A deleted class gives no access to the organization's papers; a
            # student with another live class in the subject keeps them.
            .where(GroupMember.student_id == student_id, Group.deleted_at.is_(None))
        )
    ).all()
    return {(org_id, subject_id) for org_id, subject_id in rows}


async def class_deleted(db: AsyncSession, group_id: int) -> bool:
    """Whether the class was deleted. A deleted class's unsubmitted work vanishes
    for students; what they already handed in stays (`PROD-5`)."""
    return (await db.scalar(select(Group.deleted_at).where(Group.id == group_id))) is not None


async def _member_of_live_class(db: AsyncSession, group_id: int, student_id: int) -> bool:
    if await class_deleted(db, group_id):
        return False
    member = await db.scalar(
        select(GroupMember.id).where(
            GroupMember.group_id == group_id, GroupMember.student_id == student_id
        )
    )
    return member is not None


async def homework_open_to(db: AsyncSession, assignment: Assignment, student_id: int) -> bool:
    """Published, its class still exists, and the student is still in it."""
    if assignment.status != AssignmentStatus.published:
        return False
    return await _member_of_live_class(db, assignment.group_id, student_id)


async def past_paper_open_to(db: AsyncSession, paper: PastPaper, student_id: int) -> bool:
    """The student is taught this subject by this paper's organization in a class
    that still exists. A paper a tutor has hidden stays open: students keep it."""
    return (paper.organization_id, paper.subject_id) in await enrolled_scope(db, student_id)


async def mock_open_to(db: AsyncSession, mock: Mock, student_id: int) -> bool:
    """Published, set to a class, which still exists, with the student in it."""
    if mock.status != MockStatus.published or mock.group_id is None:
        return False
    return await _member_of_live_class(db, mock.group_id, student_id)


async def open_to(db: AsyncSession, kind: SubmissionKind, parent: object, student_id: int) -> bool:
    """The gate for whichever kind of work `parent` is."""
    if kind is HOMEWORK:
        assert isinstance(parent, Assignment)
        return await homework_open_to(db, parent, student_id)
    if kind is PAST_PAPER:
        assert isinstance(parent, PastPaper)
        return await past_paper_open_to(db, parent, student_id)
    assert kind is MOCK and isinstance(parent, Mock)
    return await mock_open_to(db, parent, student_id)
