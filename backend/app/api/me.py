from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, StudentUser, TutorUser
from app.models import (
    Group,
    GroupMember,
    Organization,
    ParentLink,
    ScheduleSlot,
    Subject,
    User,
)
from app.schemas.activity import ActivitySummary
from app.schemas.auth import UserOut, UserTimezoneUpdate
from app.schemas.groups import GroupOut, SubjectOut, UpcomingScheduleSlot
from app.schemas.mistake_rollup import MyCategoryCount, MyMistakePattern
from app.schemas.orgs import OrganizationOut, OrganizationTimezoneUpdate
from app.services import activity
from app.services.mistake_rollup import roll_up_mistakes
from app.services.subjects import visible_subject_ids
from app.services.timezones import normalize_timezone
from app.services.today import today_lessons

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
    # The home aggregate serves the same list, so the query and the organization's
    # "today" rule live in services/today.py — one copy, and neither surface can
    # drift from the other (BE-2).
    return await today_lessons(db, user.id, user.organization_id, user.time_zone)


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


@router.get("/timezone", response_model=UserOut)
async def my_timezone(db: DbSession, user: CurrentUser) -> UserOut:
    """This user's own zone override, or None to follow the organization's.

    Served from the authenticated user (SEC-7) — there is no path or body
    parameter that could name anybody else.
    """
    _ = db  # session-per-request dependency; the user row is already loaded
    return UserOut.model_validate(user)


@router.put("/timezone", response_model=UserOut)
async def set_my_timezone(body: UserTimezoneUpdate, db: DbSession, user: CurrentUser) -> UserOut:
    """Set (or clear) this user's own zone (AV-67).

    Deliberately NOT tutor-gated: the whole point is that a student or parent
    may sit in a different zone from the tutor whose organization they belong
    to. The gate in the signature is authentication itself — a caller can
    only ever change their own row. Validation matches the organization
    endpoint exactly: an unusable name is reported, never stored.
    """
    try:
        tz = normalize_timezone(body.timezone)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Not a recognised IANA timezone name"
        ) from None
    user.time_zone = tz
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/mistakes", response_model=list[MyMistakePattern])
async def my_mistakes(db: DbSession, user: StudentUser) -> list[MyMistakePattern]:
    """What kinds of mistakes this student makes, one entry per subject (4.5).

    There is no `student_id` here, in the path or anywhere else: the student is
    `user.id`, read off the token (`SEC-7`, `PROD-4`). The absence of the
    parameter is the control — there is nothing to authorize because there is
    nothing a caller could name.

    Subjects come from `visible_subject_ids`, which scopes a student to the
    groups they are actually in rather than to their organization: a student
    may be taught a subject by a tutor in another tenant (`SEC-8`).

    The numbers are `roll_up_mistakes` projected down, never a second query —
    two answers to "which mistakes count" is the `RISK-5` failure that module's
    docstring names, and a third is no better. What the projection drops is
    severity, at every level: it is an internal weighting signal, and it reads
    as a verdict to the person who made the mistakes.
    """
    subject_ids = await visible_subject_ids(db, user)
    if not subject_ids:
        return []
    subjects = (
        await db.scalars(select(Subject).where(Subject.id.in_(subject_ids)).order_by(Subject.name))
    ).all()
    # Two queries per subject, on a list a student has a handful of entries in.
    # Batching would mean a second scoping of "which mistakes count", which is
    # the one thing this endpoint must not have (see above).
    out: list[MyMistakePattern] = []
    for subject in subjects:
        rollup = await roll_up_mistakes(db, student_id=user.id, subject_id=subject.id)
        out.append(
            MyMistakePattern(
                subject_id=subject.id,
                subject_name=subject.name,
                analysed_questions=rollup.analysed_questions,
                total_mistakes=rollup.total.mistakes,
                categories=[
                    MyCategoryCount(
                        category_id=c.category_id,
                        category_name=c.category_name,
                        mistakes=c.mistakes,
                    )
                    for c in rollup.total.categories
                ],
            )
        )
    return out
