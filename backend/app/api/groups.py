import secrets

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models import (
    Group,
    GroupMember,
    Invite,
    InviteKind,
    Lesson,
    Subject,
    User,
    UserRole,
)
from app.schemas.auth import UserOut
from app.schemas.groups import (
    GroupCreate,
    GroupDetail,
    GroupOut,
    GroupUpdate,
    InviteOut,
    LessonCreate,
    LessonOut,
    StudentCreate,
    StudentPasswordReset,
    SubjectOut,
)
from app.security import hash_password

router = APIRouter(prefix="/groups", tags=["groups"])


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
    rows = (
        await db.execute(
            select(Group, func.count(GroupMember.id))
            .outerjoin(GroupMember)
            .where(Group.tutor_id == user.id)
            .group_by(Group.id)
            .options(selectinload(Group.subject))
            .order_by(Group.created_at)
        )
    ).all()
    return [
        GroupOut(
            id=g.id,
            name=g.name,
            subject=SubjectOut.model_validate(g.subject),
            member_count=count,
        )
        for g, count in rows
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
    return GroupDetail(
        id=group.id,
        name=group.name,
        subject=SubjectOut.model_validate(group.subject),
        members=[UserOut.model_validate(m) for m in members],
    )


@router.patch("/{group_id}", response_model=GroupOut)
async def update_group(group_id: int, body: GroupUpdate, db: DbSession, user: CurrentUser) -> GroupOut:
    group = await _owned_group(db, user, group_id)
    group.name = body.name
    await db.commit()
    return GroupOut(id=group.id, name=group.name, subject=SubjectOut.model_validate(group.subject))


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
