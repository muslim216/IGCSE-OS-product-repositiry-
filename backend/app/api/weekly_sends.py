"""Reading the stored weekly send (tasks 8.2, 8.4).

Every route is a seek on `weekly_sends` — nothing here builds a send or calls a
model. A reader sees their own; a tutor may also read what went to a learner
they teach and to that learner's parents (AV-62: the tutor reads the send, they
do not gate or edit it). Anything else is 404, never 403, because the ids are
enumerable (`API-7`).
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, TutorUser
from app.api.students import _tutor_student
from app.models import (
    Group,
    GroupMember,
    ParentLink,
    User,
    UserRole,
    WeeklySend,
    WeeklySendAudience,
)
from app.schemas.weekly_send import WeeklySendListItem, WeeklySendOut, WeeklySendParagraph
from app.services.weekly_send import (
    LinkedChild,
    SendView,
    linked_children,
    sends_for,
    view_for_reader,
)

router = APIRouter(tags=["weekly-sends"])

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Weekly send not found")


def _out(view: SendView) -> WeeklySendOut:
    send, facts = view.send, view.facts
    return WeeklySendOut(
        id=send.id,
        audience=send.audience,
        recipient_user_id=send.recipient_user_id,
        week_start=send.week_start,
        week_end=send.week_end,
        paragraphs=[WeeklySendParagraph(about=p["about"], text=p["text"]) for p in view.paragraphs],
        **{send.audience.value: facts},
    )


async def _visible(db: AsyncSession, reader: User, sends: list[WeeklySend]) -> list[WeeklySend]:
    """The sends that still have something this reader may see. A parent's
    links and a tutor's classes change after a send is stored, so each list is
    narrowed at read time; one lookup per parent, not per send."""
    allowed: dict[int, list[LinkedChild]] = {}
    kept: list[WeeklySend] = []
    for send in sends:
        pool = None
        if send.audience == WeeklySendAudience.parent and reader.role != UserRole.admin:
            pid = send.recipient_user_id
            if pid not in allowed:
                allowed[pid] = await linked_children(
                    db,
                    pid,
                    send.organization_id,
                    taught_by=reader.id if reader.id != pid else None,
                )
            pool = allowed[pid]
        if await view_for_reader(db, reader, send, allowed=pool) is not None:
            kept.append(send)
    return kept


async def _items(db: AsyncSession, sends: list[WeeklySend]) -> list[WeeklySendListItem]:
    ids = {s.recipient_user_id for s in sends}
    names = (
        dict((await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all())
        if ids
        else {}
    )
    return [
        WeeklySendListItem(
            id=s.id,
            audience=s.audience,
            recipient_user_id=s.recipient_user_id,
            recipient_name=names.get(s.recipient_user_id, ""),
            week_start=s.week_start,
            week_end=s.week_end,
        )
        for s in sends
    ]


async def _tutor_may_read(db: AsyncSession, tutor: User, send: WeeklySend) -> bool:
    """A tutor reads the sends of learners in their own classes and of those
    learners' parents — never another tutor's own send, and never a learner
    they do not teach."""
    if send.audience == WeeklySendAudience.tutor:
        return False
    taught = (
        select(GroupMember.student_id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(Group.tutor_id == tutor.id, Group.organization_id == tutor.organization_id)
    )
    if send.audience == WeeklySendAudience.student:
        hit = await db.scalar(
            select(User.id).where(User.id == send.recipient_user_id, User.id.in_(taught)).limit(1)
        )
    else:
        hit = await db.scalar(
            select(ParentLink.id)
            .where(
                ParentLink.parent_id == send.recipient_user_id, ParentLink.student_id.in_(taught)
            )
            .limit(1)
        )
    return hit is not None


@router.get("/weekly-sends", response_model=list[WeeklySendListItem])
async def my_weekly_sends(db: DbSession, user: CurrentUser) -> list[WeeklySendListItem]:
    """The caller's own sends, newest first — "earlier reports"."""
    sends = await sends_for(db, user.organization_id, [user.id])
    return await _items(db, await _visible(db, user, sends))


@router.get("/weekly-sends/latest", response_model=WeeklySendOut | None)
async def my_latest_weekly_send(db: DbSession, user: CurrentUser) -> WeeklySendOut | None:
    """The caller's most recent send, or null when none has gone out yet — a
    stated absence the home page renders as nothing, not as an empty report."""
    # Newest first, so the first send with anything left for this reader is the
    # latest one: a send whose every child has since been unlinked is skipped.
    sends = await sends_for(db, user.organization_id, [user.id])
    # One lookup for the loop, as `_visible` does, not one per send.
    pool = (
        await linked_children(db, user.id, user.organization_id)
        if any(s.audience == WeeklySendAudience.parent for s in sends)
        else None
    )
    for send in sends:
        view = await view_for_reader(db, user, send, allowed=pool)
        if view is not None:
            return _out(view)
    return None


@router.get("/weekly-sends/{send_id}", response_model=WeeklySendOut)
async def weekly_send(send_id: int, db: DbSession, user: CurrentUser) -> WeeklySendOut:
    send = await db.get(WeeklySend, send_id)
    # The organization gate binds before any role branch (`SEC-7`).
    if send is None or send.organization_id != user.organization_id:
        raise _NOT_FOUND
    if (
        send.recipient_user_id == user.id
        or user.role == UserRole.admin
        or (user.role == UserRole.tutor and await _tutor_may_read(db, user, send))
    ):
        view = await view_for_reader(db, user, send)
        if view is not None:
            return _out(view)
    raise _NOT_FOUND


@router.get("/students/{student_id}/weekly-sends", response_model=list[WeeklySendListItem])
async def student_weekly_sends(
    student_id: int, db: DbSession, user: TutorUser
) -> list[WeeklySendListItem]:
    """What went to one learner and to their parents, newest first."""
    student = await _tutor_student(db, user, student_id)
    parent_ids = (
        await db.scalars(
            select(ParentLink.parent_id)
            .join(User, User.id == ParentLink.parent_id)
            .where(
                ParentLink.student_id == student.id,
                User.organization_id == user.organization_id,
            )
        )
    ).all()
    sends = await sends_for(db, user.organization_id, [student.id, *parent_ids], limit=52)
    return await _items(db, await _visible(db, user, sends))
