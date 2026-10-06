"""When a message is sent (task 8.5): the events and the sweep behind them.

Two kinds of trigger, deliberately different in shape:

- **Events** — homework published, marked work ready. Announced from the code
  path where the thing happens, in the same transaction, so a message is never
  queued for something that then rolled back.
- **Moments** — homework due tomorrow, a lesson about to start, work waiting for
  review. Nothing "happens" at those moments, so a sweep looks for them. A
  sweep and not a chain, for the reason `services/narrative.py` records: a
  chain dies silently the first time a run fails past its retries.

Every call goes through `notify()` with a key that names the thing and the
reader, so an event that fires twice — a tutor re-finalizing after an override,
a sweep seeing the same lesson on two runs — sends once.

**A message must never break the work it describes.** Publishing homework and
settling marks are the product; telling someone about it is a courtesy on top.
Each announcement runs in its own savepoint and logs rather than raises.

Params are names, subjects, dates and counts only — never anything a student
wrote (threat review F9).
"""

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import async_session
from app.models import (
    Assignment,
    AssignmentStatus,
    Group,
    GroupMember,
    Job,
    JobStatus,
    NotificationKind,
    Organization,
    ParentLink,
    Subject,
    Submission,
    TeachingPlan,
    TeachingPlanStatus,
    User,
    UserRole,
)
from app.services.lesson_reminders import due_reminders
from app.services.notifications.service import notify
from app.services.submission_kind import HOMEWORK, kind_of
from app.services.timezones import effective_timezone
from app.services.today import pending_review_count
from app.services.work import parent_of
from app.workers.jobs import enqueue

log = logging.getLogger("notifications")

SWEEP_JOB = "sweep_message_triggers"

#: Homework is announced as due this far ahead of its deadline.
DUE_SOON = timedelta(hours=24)
#: The review nudge goes out once a day, and only inside these local hours: a
#: tutor is not woken at 3am because a student handed work in at 3am.
REVIEW_NUDGE_HOURS = range(8, 20)


def _zone(name: str | None) -> ZoneInfo | timezone:
    if name:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - an unloadable zone degrades to UTC
            pass
    return timezone.utc


def _aware(value: datetime) -> datetime:
    # SQLite (the test database) hands back naive datetimes; they are UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _moment(value: datetime) -> str:
    """A UTC instant as a short stable key part, whatever the column handed back."""
    return _aware(value).astimezone(timezone.utc).strftime("%Y%m%dT%H%MZ")


def due_phrase(due_at: datetime | None, zone_name: str | None) -> str:
    """How a deadline reads after the word "due". No deadline is said in words:
    the template needs something there, and a blank or a made-up date would both
    be wrong."""
    if due_at is None:
        return "whenever it is ready"
    local = _aware(due_at).astimezone(_zone(zone_name))
    return f"on {local.strftime('%a')} {local.day} {local.strftime('%b')} at {local:%H:%M}"


async def _readers(
    session: AsyncSession, organization_id: int, student_ids: Sequence[int], *, parents: bool
) -> list[tuple[User, User]]:
    """(reader, the learner it is about) for each learner and, when asked, each
    of their parents. Everyone is in the organization the event happened in —
    a parent linked across tenants is not messaged about this one (`SEC-7`)."""
    if not student_ids:
        return []
    students = (
        await session.scalars(
            select(User).where(
                User.id.in_(student_ids),
                User.organization_id == organization_id,
                User.role == UserRole.student,
            )
        )
    ).all()
    out: list[tuple[User, User]] = [(s, s) for s in students]
    if parents and students:
        by_id = {s.id: s for s in students}
        rows = (
            await session.execute(
                select(User, ParentLink.student_id)
                .join(ParentLink, ParentLink.parent_id == User.id)
                .where(
                    ParentLink.student_id.in_(by_id),
                    User.organization_id == organization_id,
                    User.role == UserRole.parent,
                )
                .order_by(User.id)
            )
        ).all()
        out.extend((parent, by_id[student_id]) for parent, student_id in rows)
    return out


def _link(reader: User, student_path: str) -> str:
    return student_path if reader.role == UserRole.student else "/parent"


async def _announce(session: AsyncSession, what: str, send) -> None:
    """Run one announcement so that it cannot fail the caller's transaction."""
    try:
        async with session.begin_nested():
            await send()
    except Exception:  # noqa: BLE001 - see the module docstring
        log.exception("could not queue a message for %s", what)


# --------------------------------------------------------------------- events


async def announce_homework_set(session: AsyncSession, assignment: Assignment) -> None:
    """Tell the class, and their parents, that homework has been published."""

    async def send() -> None:
        group = await session.get(Group, assignment.group_id)
        # A deleted class's homework is announced to no one.
        if group is None or group.deleted_at is not None:
            return
        subject = await session.get(Subject, group.subject_id)
        org = await session.get(Organization, group.organization_id)
        student_ids = (
            await session.scalars(
                select(GroupMember.student_id).where(GroupMember.group_id == group.id)
            )
        ).all()
        due = due_phrase(assignment.due_at, org.timezone if org else None)
        for reader, student in await _readers(
            session, group.organization_id, student_ids, parents=True
        ):
            await notify(
                session,
                recipient=reader,
                kind=NotificationKind.homework_set,
                params={
                    "student_name": student.name,
                    "subject_name": subject.name if subject else group.name,
                    "due_date": due,
                },
                link_path=_link(reader, f"/student/homework/{assignment.id}"),
                idempotency_key=f"homework_set:{assignment.id}:{student.id}:{reader.id}",
            )

    await _announce(session, f"assignment {assignment.id}", send)


async def announce_marked_work(
    session: AsyncSession, submission: Submission, subject_id: int
) -> None:
    """Tell the learner, and their parents, that marks have settled. Called from
    the one place both settle paths meet (`record_marks_as_evidence`), so an
    auto-finalize and a tutor's sign-off are announced alike — and a tutor
    re-finalizing after an override is the same key, so it is not announced
    twice."""

    async def send() -> None:
        student = await session.get(User, submission.student_id)
        subject = await session.get(Subject, subject_id)
        if student is None or subject is None:
            return
        path = "/student"
        if kind_of(submission) is HOMEWORK:
            assignment = await parent_of(session, submission)
            if assignment is not None:
                path = f"/student/homework/{assignment.id}"
        for reader, about in await _readers(
            session, student.organization_id, [student.id], parents=True
        ):
            await notify(
                session,
                recipient=reader,
                kind=NotificationKind.marked_work_ready,
                params={"student_name": about.name, "subject_name": subject.name},
                link_path=_link(reader, path),
                idempotency_key=f"marked_work:{submission.id}:{reader.id}",
            )

    await _announce(session, f"submission {submission.id}", send)


# -------------------------------------------------------------------- moments


async def remind_homework_due(session: AsyncSession, now: datetime) -> int:
    """Homework due in the next day, for learners who have not handed it in.
    The learner only: a parent gets the weekly record, not a nudge per piece."""
    rows = (
        await session.execute(
            select(Assignment, Group)
            .join(Group, Group.id == Assignment.group_id)
            .where(
                Assignment.status == AssignmentStatus.published,
                Assignment.due_at.is_not(None),
                Assignment.due_at > now,
                Assignment.due_at <= now + DUE_SOON,
                Group.deleted_at.is_(None),
            )
        )
    ).all()
    sent = 0
    for assignment, group in rows:
        members = set(
            (
                await session.scalars(
                    select(GroupMember.student_id).where(GroupMember.group_id == group.id)
                )
            ).all()
        )
        handed_in = set(
            (
                await session.scalars(
                    select(Submission.student_id).where(Submission.work_id == assignment.work_id)
                )
            ).all()
        )
        subject = await session.get(Subject, group.subject_id)
        org = await session.get(Organization, group.organization_id)
        due = due_phrase(assignment.due_at, org.timezone if org else None)
        for reader, student in await _readers(
            session, group.organization_id, sorted(members - handed_in), parents=False
        ):
            await notify(
                session,
                recipient=reader,
                kind=NotificationKind.homework_due,
                params={
                    "student_name": student.name,
                    "subject_name": subject.name if subject else group.name,
                    "due_date": due,
                },
                link_path=f"/student/homework/{assignment.id}",
                # The due moment is part of the key: a deadline extended after
                # its reminder went out is a new thing to remind about.
                idempotency_key=(
                    f"homework_due:{assignment.id}:{_moment(assignment.due_at)}:{reader.id}"
                ),
            )
            sent += 1
    return sent


async def _tutors_with_plans(session: AsyncSession) -> list[User]:
    return list(
        await session.scalars(
            select(User)
            .where(
                User.role == UserRole.tutor,
                User.id.in_(
                    select(Group.tutor_id)
                    .join(TeachingPlan, TeachingPlan.group_id == Group.id)
                    .where(
                        TeachingPlan.status == TeachingPlanStatus.accepted,
                        Group.deleted_at.is_(None),
                    )
                ),
            )
            .order_by(User.id)
        )
    )


async def remind_lessons(session: AsyncSession, now: datetime) -> int:
    """A planned lesson about to start, to its tutor and its learners.

    Reuses the in-app reminder's own rule (`due_reminders`) for which lessons
    count, so the phone and the screen cannot disagree about whether a lesson
    is on. That window stays open until the lesson ends; a message is only
    useful before it starts, so this stops at the start.
    """
    sent = 0
    for tutor in await _tutors_with_plans(session):
        org = await session.get(Organization, tutor.organization_id)
        # The zone `due_reminders` judged the slot in, not the organization's:
        # the tutor's own zone wins there, so it must here or the message names
        # a different time from the one the lesson was found at.
        zone = _zone(effective_timezone(tutor.time_zone, org.timezone if org else None))
        for reminder in await due_reminders(session, tutor, now):
            if now > reminder.starts_at:
                continue
            group = await session.get(Group, reminder.group_id)
            subject = await session.get(Subject, group.subject_id) if group else None
            params = {
                "subject_name": subject.name if subject else reminder.group_name,
                "start_time": f"{reminder.starts_at.astimezone(zone):%H:%M}",
            }
            student_ids = (
                await session.scalars(
                    select(GroupMember.student_id).where(GroupMember.group_id == reminder.group_id)
                )
            ).all()
            learners = await _readers(session, tutor.organization_id, student_ids, parents=False)
            for reader, link in [(tutor, "/tutor"), *((s, "/student") for s, _ in learners)]:
                await notify(
                    session,
                    recipient=reader,
                    kind=NotificationKind.lesson_reminder,
                    params=params,
                    link_path=link,
                    # The start is part of the key: a lesson moved after its
                    # reminder went out needs a new one.
                    idempotency_key=(
                        f"lesson_reminder:{reminder.slot_id}:"
                        f"{_moment(reminder.starts_at)}:{reader.id}"
                    ),
                )
                sent += 1
    return sent


async def nudge_review_queue(session: AsyncSession, now: datetime) -> int:
    """Once a day, in waking hours, tell a tutor that work is waiting for them."""
    sent = 0
    tutors = (
        await session.scalars(select(User).where(User.role == UserRole.tutor).order_by(User.id))
    ).all()
    for tutor in tutors:
        org = await session.get(Organization, tutor.organization_id)
        local = now.astimezone(_zone(org.timezone if org else None))
        if local.hour not in REVIEW_NUDGE_HOURS:
            continue
        waiting = await pending_review_count(session, tutor.organization_id)
        if waiting <= 0:
            continue
        await notify(
            session,
            recipient=tutor,
            kind=NotificationKind.review_queue,
            params={"pending_count": str(waiting)},
            link_path="/tutor/review",
            # The tutor's own calendar day: at most one nudge a day.
            idempotency_key=f"review_queue:{tutor.id}:{local.date().isoformat()}",
        )
        sent += 1
    return sent


# ---------------------------------------------------------------------- sweep


async def _has_pending(session: AsyncSession) -> bool:
    return (
        await session.scalar(
            select(Job.id).where(Job.type == SWEEP_JOB, Job.status == JobStatus.pending).limit(1)
        )
    ) is not None


async def ensure_message_trigger_sweep_scheduled(session: AsyncSession) -> None:
    """Startup floor: schedule a sweep if none is waiting. Idempotent."""
    if await _has_pending(session):
        return
    await enqueue(session, SWEEP_JOB, {})


async def _commit_successor_sweep() -> None:
    """Queue the next sweep in its own committed transaction, before the work,
    so the schedule survives the work failing (see `services/narrative.py`)."""
    async with async_session() as session:
        if await _has_pending(session):
            return
        interval = get_settings().message_trigger_sweep_interval_minutes
        await enqueue(
            session,
            SWEEP_JOB,
            {},
            run_after=datetime.now(timezone.utc) + timedelta(minutes=interval),
        )
        await session.commit()


async def sweep_message_triggers(session: AsyncSession, payload: dict) -> None:
    """Job handler. Each reminder kind runs in its own savepoint: lesson
    reminders must still go out on a day the homework query is broken."""
    await _commit_successor_sweep()
    if not get_settings().message_triggers_enabled:
        return
    now = datetime.now(timezone.utc)
    for name, step in (
        ("homework due", remind_homework_due),
        ("lesson reminders", remind_lessons),
        ("review nudge", nudge_review_queue),
    ):
        try:
            async with session.begin_nested():
                await step(session, now)
        except Exception:  # noqa: BLE001 - one kind failing must not cost the others
            log.exception("message trigger sweep: %s failed", name)
