import secrets
from collections import defaultdict
from datetime import datetime, time

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models import (
    Assignment,
    AssignmentStatus,
    Group,
    GroupMember,
    Invite,
    InviteKind,
    Lesson,
    Subject,
    Submission,
    SubmissionStatus,
    User,
    UserRole,
)
from app.models.base import utcnow
from app.schemas.auth import UserOut
from app.schemas.groups import (
    GroupCreate,
    GroupDetail,
    GroupOut,
    GroupSummary,
    GroupUpdate,
    InviteOut,
    LessonCreate,
    LessonOut,
    NextLesson,
    StudentCreate,
    StudentPasswordReset,
    SubjectOut,
)
from app.security import hash_password

router = APIRouter(prefix="/groups", tags=["groups"])


def _soonest(lessons: list[Lesson], now: datetime) -> NextLesson | None:
    """Pick the next occurrence of a weekly timetable.

    Lessons repeat weekly (weekday + start_time, no date), so "next" means the
    smallest number of days ahead; a slot earlier today has already passed and
    rolls round to next week.
    """
    if not lessons:
        return None
    today, current = now.weekday(), now.time()

    def days_away(lesson: Lesson) -> tuple[int, time]:
        days = (lesson.weekday - today) % 7
        if days == 0 and lesson.start_time <= current:
            days = 7
        return days, lesson.start_time

    nxt = min(lessons, key=days_away)
    return NextLesson(
        weekday=nxt.weekday,
        start_time=nxt.start_time,
        duration_min=nxt.duration_min,
        title=nxt.title,
    )


async def _summaries(db, group_ids: list[int]) -> dict[int, GroupSummary]:
    """Per-group counts for the class cards.

    Each aggregate is its own query rather than one wide join: joining members,
    assignments and submissions together would multiply the rows and inflate
    every count.
    """
    if not group_ids:
        return {}

    members = dict(
        (
            await db.execute(
                select(GroupMember.group_id, func.count(GroupMember.id))
                .where(GroupMember.group_id.in_(group_ids))
                .group_by(GroupMember.group_id)
            )
        ).all()
    )
    published = dict(
        (
            await db.execute(
                select(Assignment.group_id, func.count(Assignment.id))
                .where(
                    Assignment.group_id.in_(group_ids),
                    Assignment.status == AssignmentStatus.published,
                )
                .group_by(Assignment.group_id)
            )
        ).all()
    )
    awaiting = dict(
        (
            await db.execute(
                select(Assignment.group_id, func.count(Submission.id))
                .join(Assignment, Assignment.id == Submission.assignment_id)
                .where(
                    Assignment.group_id.in_(group_ids),
                    Submission.status != SubmissionStatus.finalized,
                )
                .group_by(Assignment.group_id)
            )
        ).all()
    )

    by_group: dict[int, list[Lesson]] = defaultdict(list)
    for lesson in (
        await db.scalars(select(Lesson).where(Lesson.group_id.in_(group_ids)))
    ).all():
        by_group[lesson.group_id].append(lesson)

    now = utcnow()
    return {
        gid: GroupSummary(
            member_count=members.get(gid, 0),
            published_assignment_count=published.get(gid, 0),
            awaiting_review_count=awaiting.get(gid, 0),
            next_lesson=_soonest(by_group.get(gid, []), now),
        )
        for gid in group_ids
    }


def _require_tutor(user: User) -> None:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")


async def _owned_group(db, user: User, group_id: int) -> Group:
    _require_tutor(user)
    group = await db.get(Group, group_id, options=[selectinload(Group.subject)])
    if group is None or (group.tutor_id != user.id and user.role != UserRole.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(body: GroupCreate, db: DbSession, user: CurrentUser) -> GroupOut:
    _require_tutor(user)
    subject = await db.get(Subject, body.subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    group = Group(tutor_id=user.id, subject_id=subject.id, name=body.name)
    db.add(group)
    await db.commit()
    return GroupOut(id=group.id, name=group.name, subject=SubjectOut.model_validate(subject))


@router.get("", response_model=list[GroupOut])
async def list_groups(db: DbSession, user: CurrentUser) -> list[GroupOut]:
    _require_tutor(user)
    groups = (
        await db.scalars(
            select(Group)
            .where(Group.tutor_id == user.id)
            .options(selectinload(Group.subject))
            .order_by(Group.created_at)
        )
    ).all()
    summaries = await _summaries(db, [g.id for g in groups])
    return [
        GroupOut(
            id=g.id,
            name=g.name,
            subject=SubjectOut.model_validate(g.subject),
            **summaries[g.id].model_dump(),
        )
        for g in groups
    ]


@router.get("/{group_id}", response_model=GroupDetail)
async def group_detail(group_id: int, db: DbSession, user: CurrentUser) -> GroupDetail:
    group = await _owned_group(db, user, group_id)
    members = (
        await db.scalars(
            select(User)
            .join(GroupMember, GroupMember.student_id == User.id)
            .where(GroupMember.group_id == group.id)
            .order_by(User.name)
        )
    ).all()
    summary = (await _summaries(db, [group.id]))[group.id]
    return GroupDetail(
        id=group.id,
        name=group.name,
        subject=SubjectOut.model_validate(group.subject),
        members=[UserOut.model_validate(m) for m in members],
        **summary.model_dump(),
    )


@router.patch("/{group_id}", response_model=GroupOut)
async def update_group(group_id: int, body: GroupUpdate, db: DbSession, user: CurrentUser) -> GroupOut:
    group = await _owned_group(db, user, group_id)
    group.name = body.name
    await db.commit()
    summary = (await _summaries(db, [group.id]))[group.id]
    return GroupOut(
        id=group.id,
        name=group.name,
        subject=SubjectOut.model_validate(group.subject),
        **summary.model_dump(),
    )


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: int, db: DbSession, user: CurrentUser) -> None:
    group = await _owned_group(db, user, group_id)
    await db.delete(group)
    await db.commit()


@router.post("/{group_id}/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invite(group_id: int, db: DbSession, user: CurrentUser) -> InviteOut:
    group = await _owned_group(db, user, group_id)
    invite = Invite(
        code=secrets.token_urlsafe(8),
        kind=InviteKind.student_join,
        group_id=group.id,
        created_by_id=user.id,
    )
    db.add(invite)
    await db.commit()
    return InviteOut(code=invite.code, kind=invite.kind.value, expires_at=invite.expires_at)


@router.delete("/{group_id}/members/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(group_id: int, student_id: int, db: DbSession, user: CurrentUser) -> None:
    group = await _owned_group(db, user, group_id)
    member = await db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group.id, GroupMember.student_id == student_id
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student is not in this group")
    await db.delete(member)
    await db.commit()


@router.post("/{group_id}/students", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_student_account(
    group_id: int, body: StudentCreate, db: DbSession, user: CurrentUser
) -> UserOut:
    """Create a username-only account for a student without email, and add them to the group."""
    group = await _owned_group(db, user, group_id)
    username = body.username.lower()
    existing = await db.scalar(select(User).where(func.lower(User.username) == username))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This username is already taken")
    student = User(
        username=username,
        password_hash=hash_password(body.password),
        role=UserRole.student,
        name=body.name,
        created_by_id=user.id,
    )
    db.add(student)
    await db.flush()
    db.add(GroupMember(group_id=group.id, student_id=student.id))
    await db.commit()
    return UserOut.model_validate(student)


@router.post("/{group_id}/students/{student_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_student_password(
    group_id: int, student_id: int, body: StudentPasswordReset, db: DbSession, user: CurrentUser
) -> None:
    """Tutors can reset passwords for username-only accounts of students in their groups."""
    group = await _owned_group(db, user, group_id)
    member = await db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group.id, GroupMember.student_id == student_id
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student is not in this group")
    student = await db.get(User, student_id)
    if student is None or student.email is not None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Password resets are only available for accounts without an email address",
        )
    student.password_hash = hash_password(body.password)
    await db.commit()


@router.post("/{group_id}/lessons", response_model=LessonOut, status_code=status.HTTP_201_CREATED)
async def create_lesson(
    group_id: int, body: LessonCreate, db: DbSession, user: CurrentUser
) -> LessonOut:
    group = await _owned_group(db, user, group_id)
    lesson = Lesson(
        group_id=group.id,
        weekday=body.weekday,
        start_time=body.start_time,
        duration_min=body.duration_min,
        title=body.title,
    )
    db.add(lesson)
    await db.commit()
    return LessonOut.model_validate(lesson)


@router.get("/{group_id}/lessons", response_model=list[LessonOut])
async def list_lessons(group_id: int, db: DbSession, user: CurrentUser) -> list[LessonOut]:
    group = await _owned_group(db, user, group_id)
    lessons = (
        await db.scalars(
            select(Lesson)
            .where(Lesson.group_id == group.id)
            .order_by(Lesson.weekday, Lesson.start_time)
        )
    ).all()
    return [LessonOut.model_validate(lesson) for lesson in lessons]


@router.delete("/{group_id}/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(group_id: int, lesson_id: int, db: DbSession, user: CurrentUser) -> None:
    group = await _owned_group(db, user, group_id)
    lesson = await db.scalar(
        select(Lesson).where(Lesson.id == lesson_id, Lesson.group_id == group.id)
    )
    if lesson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    await db.delete(lesson)
    await db.commit()
