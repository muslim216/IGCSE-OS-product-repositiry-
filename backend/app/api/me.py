from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models import Group, GroupMember, Lesson, ParentLink, User, UserRole
from app.schemas.auth import UserOut
from app.schemas.groups import GroupOut, SubjectOut, UpcomingLesson

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
        GroupOut(id=g.id, name=g.name, subject=SubjectOut.model_validate(g.subject))
        for g in groups
    ]


@router.get("/lessons", response_model=list[UpcomingLesson])
async def my_lessons(db: DbSession, user: CurrentUser) -> list[UpcomingLesson]:
    rows = (
        await db.execute(
            select(Lesson, Group)
            .join(Group, Group.id == Lesson.group_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.student_id == user.id)
            .options(selectinload(Group.subject))
            .order_by(Lesson.weekday, Lesson.start_time)
        )
    ).all()
    return [
        UpcomingLesson(
            group_id=group.id,
            group_name=group.name,
            subject_name=group.subject.name,
            weekday=lesson.weekday,
            start_time=lesson.start_time,
            duration_min=lesson.duration_min,
            title=lesson.title,
        )
        for lesson, group in rows
    ]


@router.get("/today-lessons", response_model=list[UpcomingLesson])
async def my_today_lessons(db: DbSession, user: CurrentUser) -> list[UpcomingLesson]:
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    today_weekday = datetime.now(timezone.utc).weekday()
    rows = (
        await db.execute(
            select(Lesson, Group, func.count(GroupMember.id))
            .join(Group, Group.id == Lesson.group_id)
            .outerjoin(GroupMember, GroupMember.group_id == Group.id)
            .where(Group.tutor_id == user.id, Lesson.weekday == today_weekday)
            .options(selectinload(Group.subject))
            .group_by(Lesson.id, Group.id)
            .order_by(Lesson.start_time)
        )
    ).all()
    return [
        UpcomingLesson(
            group_id=group.id,
            group_name=f"{group.name} ({count} student{'s' if count != 1 else ''})",
            subject_name=group.subject.name,
            weekday=lesson.weekday,
            start_time=lesson.start_time,
            duration_min=lesson.duration_min,
            title=lesson.title,
        )
        for lesson, group, count in rows
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
