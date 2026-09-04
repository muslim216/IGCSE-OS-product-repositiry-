"""Which subjects a caller may see (task 2.2, AV-6, SEC-7, SEC-8).

Subjects used to be global — five built-in syllabuses shared by every tenant —
so listing them needed no scoping at all. They are now owned by the tutor who
created them, and "owned" does not answer the question on its own, because the
three roles reach a subject by different routes.
"""

from sqlalchemy import select

from app.models import Group, GroupMember, ParentLink, Subject, User, UserRole


async def visible_subject_ids(db, user: User) -> set[int]:
    """The subject ids this user may see, by role.

    A **tutor** sees their own organization's subjects, derived from the
    authenticated user and never from a path or body parameter (`PROD-4`,
    `SEC-7`).

    A **student** sees the subjects of the groups they are actually in, which is
    deliberately *not* the same as their own organization. Joining a second
    tutor's group with an invite does not move a student's organization, so
    filtering on `user.organization_id` would hide that tutor's subject from a
    student being taught it. This is the same reasoning `_enrolled_scope` in
    `api/past_papers.py` records for past papers (`SEC-8`); the difference is
    that a subject id is globally unique, so the id alone is enough here and the
    (organization, subject) pair is not needed.

    A **parent** sees what their linked children see, and nothing else.
    """
    if user.role in (UserRole.tutor, UserRole.admin):
        rows = await db.scalars(
            select(Subject.id).where(Subject.organization_id == user.organization_id)
        )
        return set(rows.all())

    if user.role == UserRole.student:
        student_ids: list[int] = [user.id]
    else:
        student_ids = list(
            (
                await db.scalars(
                    select(ParentLink.student_id).where(ParentLink.parent_id == user.id)
                )
            ).all()
        )
        if not student_ids:
            return set()

    rows = await db.scalars(
        select(Group.subject_id)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.student_id.in_(student_ids))
    )
    return set(rows.all())
