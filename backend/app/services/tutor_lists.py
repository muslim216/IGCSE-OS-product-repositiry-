from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Assignment, Group, GroupMember, Subject, Submission, User, UserRole
from app.models.homework import SETTLED_STATUSES
from app.schemas.tutor_lists import TutorHomeworkRow, TutorStudentClass, TutorStudentRow

#: Hard caps standing in for cursor pagination (API-13), so each list stays
#: bounded (API-12). The clients mirror both numbers: a list exactly this long
#: may have been cut short, which is how the Library tells its reader the same.
HOMEWORK_LIST_LIMIT = 200
STUDENT_LIST_LIMIT = 500


def _visible_groups(user: User) -> Select:
    """Every class in the caller's own organization when an admin, otherwise
    only their own (`SEC-7`) — the rule `assignments_needing_attention` applies."""
    query = select(Group.id).where(Group.organization_id == user.organization_id)
    if user.role != UserRole.admin:
        query = query.where(Group.tutor_id == user.id)
    return query


async def tutor_homework(db: AsyncSession, user: User) -> list[TutorHomeworkRow]:
    """Homework across the caller's classes, newest first, at most
    `HOMEWORK_LIST_LIMIT`. Three queries however many rows come back: the page
    of homework, then the class sizes and the submission tallies for exactly
    that page (PERF-1)."""
    rows = (
        await db.execute(
            select(Assignment, Group.name, Subject.name)
            .join(Group, Group.id == Assignment.group_id)
            .join(Subject, Subject.id == Group.subject_id)
            .where(Assignment.group_id.in_(_visible_groups(user)))
            .order_by(Assignment.created_at.desc(), Assignment.id.desc())
            .limit(HOMEWORK_LIST_LIMIT)
        )
    ).all()
    if not rows:
        return []

    group_ids = {a.group_id for a, _, _ in rows}
    enrolled = {
        row.group_id: row.members
        for row in (
            await db.execute(
                select(GroupMember.group_id, func.count(GroupMember.id).label("members"))
                .where(GroupMember.group_id.in_(group_ids))
                .group_by(GroupMember.group_id)
            )
        ).all()
    }
    # Joined through `work_id`, never `assignment_id`: a submission is
    # polymorphic (`API-20`). One attempt per student per work, so a count of
    # rows is a count of students.
    tallies = {
        work_id: (submitted, int(marked))
        for work_id, submitted, marked in (
            await db.execute(
                select(
                    Submission.work_id,
                    func.count(Submission.id),
                    func.coalesce(
                        func.sum(case((Submission.status.in_(SETTLED_STATUSES), 1), else_=0)), 0
                    ),
                )
                .where(Submission.work_id.in_({a.work_id for a, _, _ in rows}))
                .group_by(Submission.work_id)
            )
        ).all()
    }
    return [
        TutorHomeworkRow(
            id=a.id,
            title=a.title,
            status=a.status.value,
            due_at=a.due_at,
            created_at=a.created_at,
            group_id=a.group_id,
            group_name=group_name,
            subject_name=subject_name,
            enrolled_count=enrolled.get(a.group_id, 0),
            submitted_count=tallies.get(a.work_id, (0, 0))[0],
            marked_count=tallies.get(a.work_id, (0, 0))[1],
        )
        for a, group_name, subject_name in rows
    ]


async def tutor_students(db: AsyncSession, user: User) -> list[TutorStudentRow]:
    """Every student in the caller's classes, once each, by name, at most
    `STUDENT_LIST_LIMIT`, each with the visible classes they sit in. The cap
    applies to students, not memberships, so a student in two classes is one row
    and never half a row. Two queries however many students there are."""
    visible = _visible_groups(user)
    students = (
        await db.execute(
            select(User.id, User.name)
            .join(GroupMember, GroupMember.student_id == User.id)
            .where(GroupMember.group_id.in_(visible), User.role == UserRole.student)
            .group_by(User.id, User.name)
            .order_by(func.lower(User.name), User.id)
            .limit(STUDENT_LIST_LIMIT)
        )
    ).all()
    if not students:
        return []

    classes: dict[int, list[TutorStudentClass]] = {}
    memberships = (
        await db.execute(
            select(GroupMember.student_id, Group.id, Group.name, Subject.name)
            .join(Group, Group.id == GroupMember.group_id)
            .join(Subject, Subject.id == Group.subject_id)
            .where(
                GroupMember.student_id.in_([s.id for s in students]),
                GroupMember.group_id.in_(visible),
            )
            .order_by(Group.name, Group.id)
        )
    ).all()
    for student_id, group_id, group_name, subject_name in memberships:
        classes.setdefault(student_id, []).append(
            TutorStudentClass(group_id=group_id, group_name=group_name, subject_name=subject_name)
        )
    return [TutorStudentRow(id=s.id, name=s.name, classes=classes.get(s.id, [])) for s in students]
