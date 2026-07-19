from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models import Group, GroupMember, Lesson, ParentLink, User
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
