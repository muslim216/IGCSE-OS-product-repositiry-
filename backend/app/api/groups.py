import secrets

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.analytics import group_analytics
from app.api.deps import CurrentUser, DbSession
from app.models import (
    AiFeature,
    Group,
    GroupMember,
    Invite,
    InviteKind,
    ScheduleSlot,
    Subject,
    User,
    UserRole,
)
from app.schemas.auth import UserOut
from app.schemas.groups import (
    ClassBrief,
    GroupCreate,
    GroupDetail,
    GroupOut,
    GroupUpdate,
    InviteOut,
    ScheduleSlotCreate,
    ScheduleSlotOut,
    StudentCreate,
    StudentPasswordReset,
    SubjectOut,
)
from app.security import hash_password
from app.services.ai import AIUnavailableError, record_usage, text_complete

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
    group = Group(
        organization_id=user.organization_id, tutor_id=user.id, subject_id=subject.id, name=body.name
    )
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
        organization_id=user.organization_id,
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


@router.post(
    "/{group_id}/lessons", response_model=ScheduleSlotOut, status_code=status.HTTP_201_CREATED
)
async def create_schedule_slot(
    group_id: int, body: ScheduleSlotCreate, db: DbSession, user: CurrentUser
) -> ScheduleSlotOut:
    group = await _owned_group(db, user, group_id)
    slot = ScheduleSlot(
        group_id=group.id,
        weekday=body.weekday,
        start_time=body.start_time,
        duration_min=body.duration_min,
        title=body.title,
    )
    db.add(slot)
    await db.commit()
    return ScheduleSlotOut.model_validate(slot)


@router.get("/{group_id}/lessons", response_model=list[ScheduleSlotOut])
async def list_schedule_slots(group_id: int, db: DbSession, user: CurrentUser) -> list[ScheduleSlotOut]:
    group = await _owned_group(db, user, group_id)
    slots = (
        await db.scalars(
            select(ScheduleSlot)
            .where(ScheduleSlot.group_id == group.id)
            .order_by(ScheduleSlot.weekday, ScheduleSlot.start_time)
        )
    ).all()
    return [ScheduleSlotOut.model_validate(slot) for slot in slots]


@router.post("/{group_id}/brief", response_model=ClassBrief)
async def class_brief(group_id: int, db: DbSession, user: CurrentUser) -> ClassBrief:
    """A short AI-written note to jog the tutor's memory before a lesson,
    grounded in the group's weakest topics. Basic version: no learning-style
    detection or multi-year trends yet."""
    group = await _owned_group(db, user, group_id)
    analytics = await group_analytics(group_id, db, user)

    if not analytics.weak_topics and not analytics.weak_students:
        return ClassBrief(
            brief="Not enough evidence yet to write a brief for this class — "
            "once homework or mocks are marked, a summary will appear here."
        )

    weak_topics_text = "\n".join(
        f"- {t.topic_title} ({t.topic_code}): avg {t.avg_score}% across {t.student_count} students"
        for t in analytics.weak_topics[:5]
    )
    weak_students_text = "\n".join(
        f"- {s.student_name}: {s.score}% overall" for s in analytics.weak_students[:5]
    )

    prompt = (
        f"Group: {group.name} ({group.subject.name if group.subject else ''})\n\n"
        f"Weakest topics across the class:\n{weak_topics_text or '(none yet)'}\n\n"
        f"Students with the lowest overall readiness:\n{weak_students_text or '(none yet)'}\n\n"
        "Write a short (3-5 sentence) pre-lesson brief for the tutor: what to focus on today "
        "and who might need extra attention. Plain prose, no headings."
    )
    try:
        response = await text_complete(surface="class_brief", prompt=prompt, max_tokens=400)
    except AIUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    await record_usage(
        db,
        response,
        organization_id=group.organization_id,
        tutor_id=group.tutor_id,
        student_id=None,
        feature=AiFeature.report,
    )
    await db.commit()
    return ClassBrief(brief=response.text.strip())


@router.delete("/{group_id}/lessons/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule_slot(group_id: int, slot_id: int, db: DbSession, user: CurrentUser) -> None:
    group = await _owned_group(db, user, group_id)
    slot = await db.scalar(
        select(ScheduleSlot).where(ScheduleSlot.id == slot_id, ScheduleSlot.group_id == group.id)
    )
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    await db.delete(slot)
    await db.commit()
