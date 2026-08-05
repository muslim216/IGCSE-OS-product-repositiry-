from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, TutorUser
from app.models import Group, GroupMember, ParentLink, ScheduleSlot, User
from app.schemas.activity import ActivitySummary
from app.schemas.auth import UserOut
from app.schemas.groups import GroupOut, SubjectOut, UpcomingScheduleSlot
from app.services import activity

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/groups", response_model=list[GroupOut])
async def my_groups(db: DbSession, user: CurrentUser) -> list[GroupOut]:
    groups = (
        await db.scalars(
            select(Group)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.student_id == user.id)
            .options(selectinload(Group.subject))
            .order_by(Group.name)
        )
    ).all()
    return [
        GroupOut(id=g.id, name=g.name, subject=SubjectOut.model_validate(g.subject)) for g in groups
    ]


@router.get("/lessons", response_model=list[UpcomingScheduleSlot])
async def my_lessons(db: DbSession, user: CurrentUser) -> list[UpcomingScheduleSlot]:
    rows = (
        await db.execute(
            select(ScheduleSlot, Group)
            .join(Group, Group.id == ScheduleSlot.group_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.student_id == user.id)
            .options(selectinload(Group.subject))
            .order_by(ScheduleSlot.weekday, ScheduleSlot.start_time)
        )
    ).all()
    return [
        UpcomingScheduleSlot(
            id=slot.id,
            group_id=group.id,
            group_name=group.name,
            subject_name=group.subject.name,
            weekday=slot.weekday,
            start_time=slot.start_time,
            duration_min=slot.duration_min,
            title=slot.title,
        )
        for slot, group in rows
    ]


@router.get("/today-lessons", response_model=list[UpcomingScheduleSlot])
async def my_today_lessons(db: DbSession, user: TutorUser) -> list[UpcomingScheduleSlot]:
    today_weekday = datetime.now(timezone.utc).weekday()
    rows = (
        await db.execute(
            select(ScheduleSlot, Group, func.count(GroupMember.id))
            .join(Group, Group.id == ScheduleSlot.group_id)
            .outerjoin(GroupMember, GroupMember.group_id == Group.id)
            .where(Group.tutor_id == user.id, ScheduleSlot.weekday == today_weekday)
            .options(selectinload(Group.subject))
            .group_by(ScheduleSlot.id, Group.id)
            .order_by(ScheduleSlot.start_time)
        )
    ).all()
    return [
        UpcomingScheduleSlot(
            id=slot.id,
            group_id=group.id,
            group_name=f"{group.name} ({count} student{'s' if count != 1 else ''})",
            subject_name=group.subject.name,
            weekday=slot.weekday,
            start_time=slot.start_time,
            duration_min=slot.duration_min,
            title=slot.title,
        )
        for slot, group, count in rows
    ]


@router.get("/children", response_model=list[UserOut])
async def my_children(db: DbSession, user: CurrentUser) -> list[UserOut]:
    children = (
        await db.scalars(
            select(User)
            .join(ParentLink, ParentLink.student_id == User.id)
            .where(ParentLink.parent_id == user.id)
            .order_by(User.name)
        )
    ).all()
    return [UserOut.model_validate(c) for c in children]


@router.get("/activity", response_model=ActivitySummary)
async def my_activity(db: DbSession, user: CurrentUser) -> ActivitySummary:
    """What needs this user's attention. See services/activity.py."""
    return await activity.for_user(db, user)
