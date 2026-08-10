from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, TutorUser
from app.models import Group, GroupMember, Organization, ParentLink, ScheduleSlot, User
from app.schemas.activity import ActivitySummary
from app.schemas.auth import UserOut
from app.schemas.groups import GroupOut, SubjectOut, UpcomingScheduleSlot
from app.schemas.orgs import OrganizationOut, OrganizationTimezoneUpdate
from app.services import activity
from app.services.timezones import normalize_timezone, today_weekday

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
    # "Today" is the tutor's today, not the server's. A tutor in Cairo opening
    # this at 01:00 local is on tomorrow's weekday while UTC is still on
    # yesterday's, and this endpoint's whole answer is which day it is.
    org = await db.get(Organization, user.organization_id)
    weekday = today_weekday(org.timezone if org else None)
    rows = (
        await db.execute(
            select(ScheduleSlot, Group, func.count(GroupMember.id))
            .join(Group, Group.id == ScheduleSlot.group_id)
            .outerjoin(GroupMember, GroupMember.group_id == Group.id)
            .where(Group.tutor_id == user.id, ScheduleSlot.weekday == weekday)
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


@router.get("/organization", response_model=OrganizationOut)
async def my_organization(db: DbSession, user: TutorUser) -> OrganizationOut:
    """The caller's own organization. Read from the authenticated user's
    organization_id, never a path or body parameter (SEC-7)."""
    org = await db.get(Organization, user.organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return OrganizationOut(id=org.id, name=org.name, timezone=org.timezone)


@router.put("/organization/timezone", response_model=OrganizationOut)
async def set_my_organization_timezone(
    body: OrganizationTimezoneUpdate, db: DbSession, user: TutorUser
) -> OrganizationOut:
    """Set (or clear) the zone every "today" in the product is computed in.

    Tutor-gated in the signature (BE-17): this changes what a whole roster
    sees. The submitted name is validated against the real tz database before
    it is stored — unlike signup, a Settings write is an explicit act, so an
    unusable value is reported rather than silently dropped.
    """
    try:
        tz = normalize_timezone(body.timezone)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Not a recognised IANA timezone name"
        ) from None
    org = await db.get(Organization, user.organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    org.timezone = tz
    await db.commit()
    await db.refresh(org)
    return OrganizationOut(id=org.id, name=org.name, timezone=org.timezone)
