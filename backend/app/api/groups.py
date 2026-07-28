from collections import defaultdict
from datetime import datetime, time

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.analytics import group_analytics
from app.api.deps import CurrentUser, DbSession
from app.models import (
    AiFeature,
    Assignment,
    AssignmentStatus,
    Group,
    GroupMember,
    InviteKind,
    ScheduleSlot,
    Subject,
    Submission,
    SubmissionStatus,
    User,
    UserRole,
)
from app.models.base import utcnow
from app.schemas.auth import UserOut
from app.schemas.groups import (
    ClassBrief,
    GroupCreate,
    GroupDetail,
    GroupOut,
    GroupSummary,
    GroupUpdate,
    InviteOut,
    NextLesson,
    ScheduleSlotCreate,
    ScheduleSlotOut,
    StudentCreate,
    StudentPasswordReset,
    SubjectOut,
)
from app.security import hash_password
from app.services.ai import AIUnavailableError, record_usage, text_complete
from app.services.invites import build_invite

router = APIRouter(prefix="/groups", tags=["groups"])

#: Submission states that are waiting on the tutor's eyes, mirroring the
#: attention endpoint: an AI draft to confirm, an AI failure to handle, or
#: auto-marking's uncertain rows. Finalized and auto-finalized work is done;
#: submitted/marking is still in flight.
_AWAITING_REVIEW = (
    SubmissionStatus.ai_marked,
    SubmissionStatus.ai_failed,
    SubmissionStatus.needs_review,
)


def _soonest(slots: list[ScheduleSlot], now: datetime) -> NextLesson | None:
    """Pick the next occurrence of a weekly timetable.

    Slots repeat weekly (weekday + start_time, no date), so "next" means the
    smallest number of days ahead; a slot earlier today has already passed and
    rolls round to next week.
    """
    if not slots:
        return None
    today, current = now.weekday(), now.time()

    def days_away(slot: ScheduleSlot) -> tuple[int, time]:
        days = (slot.weekday - today) % 7
        if days == 0 and slot.start_time <= current:
            days = 7
        return days, slot.start_time

    nxt = min(slots, key=days_away)
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
                    Submission.status.in_(_AWAITING_REVIEW),
                )
                .group_by(Assignment.group_id)
            )
        ).all()
    )

    by_group: dict[int, list[ScheduleSlot]] = defaultdict(list)
    for slot in (
        await db.scalars(select(ScheduleSlot).where(ScheduleSlot.group_id.in_(group_ids)))
    ).all():
        by_group[slot.group_id].append(slot)

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
    group = Group(
        organization_id=user.organization_id, tutor_id=user.id, subject_id=subject.id, name=body.name
    )
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
    summaries = await _summaries(db, [group.id])
    return GroupDetail(
        id=group.id,
        name=group.name,
        subject=SubjectOut.model_validate(group.subject),
        members=[UserOut.model_validate(m) for m in members],
        **summaries[group.id].model_dump(),
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
    invite = build_invite(InviteKind.student_join, created_by_id=user.id, group_id=group.id)
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
    """Tutors can reset passwords for username-only accounts of students in their groups.

    A reset is how a tutor evicts whoever else has been using a shared or stolen
    account, so it revokes every token that account already holds — otherwise the
    old refresh token keeps minting access tokens for its full 30 days and the
    new password changes nothing for the attacker.
    """
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
    student.token_version += 1
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
