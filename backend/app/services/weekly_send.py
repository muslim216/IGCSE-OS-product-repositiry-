"""The weekly send: built once a week per organization, stored, then announced.

`weekly_send_facts.py` computes what a week contained; this module decides
*when* a week is closed, stores one `WeeklySend` per reader, and hands each to
the notification outbox (task 8.2, AV-49/50/62–66).

**A sweep, not a chain** — the same decision `services/narrative.py` records,
for the same reason. A chain keeps the whole schedule inside one job row, and
`workers/jobs.py` marks a job failed at MAX_ATTEMPTS with nothing watching it,
so one bad week would end an account's sends permanently and silently. The
sweep re-derives which organizations are due from the `weekly_sends` table on
every run (`BE-9`): a failed sweep costs one cycle, a failed organization costs
that organization one cycle, and both self-correct.

**One writer** (AV-99, task 8.3). The send has no generator of its own. Its
paragraphs are copies of the stored narrative rows — the same text the tutor's
class page and the parent's screen show — so the message and the screen cannot
disagree about the same child, and a week costs one model call per target, not
two. The sweep asks the narrative writer to refresh shortly before the build;
that refresh is the ordinary non-forced job, a no-op when nothing new was
marked.

**The tutor's clock** (AV-88/89/90). The week closes at the organization's
chosen weekday and hour in the organization's own zone, and everyone in it is
sent at that one moment. This is the one place a reader's own time zone is
deliberately ignored: a parent abroad gets the report when the tutor's week
ends, not seven hours into the next one.
"""

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from pydantic import TypeAdapter
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import async_session
from app.models import (
    Group,
    GroupMember,
    Job,
    JobStatus,
    Narrative,
    NarrativeAudience,
    NotificationKind,
    Organization,
    ParentLink,
    User,
    UserRole,
    WeeklySend,
    WeeklySendAudience,
)
from app.services.narrative import CLASS_NARRATIVE_JOB
from app.services.notifications import notify
from app.services.weekly_send_facts import (
    ParentFacts,
    StudentFacts,
    TutorFacts,
    build_parent_facts,
    build_student_facts,
    build_tutor_facts,
    organization_week_window,
)
from app.workers.jobs import enqueue

log = logging.getLogger("weekly_send")

SWEEP_JOB = "sweep_weekly_sends"
BUILD_JOB = "build_weekly_sends"

#: A week that closed longer ago than this is not sent late. Without it the
#: first deploy would mail every account a "weekly" report for a week that ended
#: days ago, and an outage would be followed by a burst of stale ones.
LATE_GRACE = timedelta(hours=24)

_ADAPTERS: dict[WeeklySendAudience, TypeAdapter] = {
    WeeklySendAudience.tutor: TypeAdapter(TutorFacts),
    WeeklySendAudience.student: TypeAdapter(StudentFacts),
    WeeklySendAudience.parent: TypeAdapter(ParentFacts),
}


def _aware(value: datetime) -> datetime:
    # SQLite (the test database) hands back naive datetimes; they are UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def dump_facts(audience: WeeklySendAudience, facts: object) -> dict:
    """The JSON form stored on the row. Round-trips through `load_facts`."""
    return _ADAPTERS[audience].dump_python(facts, mode="json")


def load_facts(
    audience: WeeklySendAudience, stored: dict
) -> TutorFacts | StudentFacts | ParentFacts:
    return _ADAPTERS[audience].validate_python(stored)


# ----------------------------------------------------------------- the message


def message_params(audience: WeeklySendAudience, facts: object) -> dict[str, str]:
    """The three values the WhatsApp template carries. Counts only — and a week
    with no lessons or no homework says 0, which is a count, not a missing
    measurement."""
    if isinstance(facts, TutorFacts):
        blocks: Sequence = facts.classes
        whose = "your classes'"
    elif isinstance(facts, StudentFacts):
        blocks = facts.classes
        whose = "your"
    elif isinstance(facts, ParentFacts):
        blocks = [c for child in facts.children for c in child.classes]
        whose = (
            f"{facts.children[0].child_name}'s" if len(facts.children) == 1 else "your children's"
        )
    else:  # pragma: no cover - the three audiences are exhaustive
        raise TypeError(f"not a weekly-send fact set: {type(facts).__name__}")
    lessons = sum(b.attendance.lessons_held for b in blocks if b.attendance is not None)
    handed_in = sum(b.homework.handed_in_count for b in blocks if b.homework is not None)
    return {"whose": whose, "lessons_count": str(lessons), "homework_done": str(handed_in)}


# ------------------------------------------------------------------ paragraphs


async def _latest_narratives(
    session: AsyncSession,
    organization_id: int,
    audience: NarrativeAudience,
    target_ids: Sequence[int],
    since: datetime,
) -> dict[int, Narrative]:
    """The newest stored narrative per target, if it was written this week.

    An older paragraph is left out rather than attached: last month's text under
    this week's numbers would read as being about this week.
    """
    if not target_ids:
        return {}
    column = (
        Narrative.group_id if audience is NarrativeAudience.tutor_class else Narrative.student_id
    )
    newest = (
        select(func.max(Narrative.id))
        .where(
            Narrative.organization_id == organization_id,
            Narrative.audience == audience,
            column.in_(target_ids),
        )
        .group_by(column)
    )
    rows = await session.scalars(select(Narrative).where(Narrative.id.in_(newest)))
    return {n.target_id: n for n in rows if _aware(n.generated_at) >= since}


def _paragraph(about: str, narrative: Narrative) -> dict:
    return {"about": about, "text": narrative.text, "narrative_id": narrative.id}


# ---------------------------------------------------------------------- build


async def _recipients(session: AsyncSession, organization_id: int) -> list[User]:
    """Everyone in the organization the week is about: its tutors, the learners
    in at least one of its classes, and the parents linked to those learners."""
    tutors = (
        await session.scalars(
            select(User).where(User.organization_id == organization_id, User.role == UserRole.tutor)
        )
    ).all()
    enrolled = (
        select(distinct(GroupMember.student_id))
        .join(Group, Group.id == GroupMember.group_id)
        .where(Group.organization_id == organization_id)
    )
    students = (
        await session.scalars(
            select(User).where(
                User.organization_id == organization_id,
                User.role == UserRole.student,
                User.id.in_(enrolled),
            )
        )
    ).all()
    parents = (
        await session.scalars(
            select(User)
            .where(
                User.organization_id == organization_id,
                User.role == UserRole.parent,
                User.id.in_(
                    select(ParentLink.parent_id).where(ParentLink.student_id.in_(enrolled))
                ),
            )
            .order_by(User.id)
        )
    ).all()
    return [*tutors, *students, *parents]


async def _build_one(
    session: AsyncSession, person: User, window: tuple[datetime, datetime]
) -> WeeklySend | None:
    """One reader's send, or None when the week has nothing to say to them."""
    start, _end = window
    paragraphs: list[dict] = []
    if person.role == UserRole.tutor:
        audience = WeeklySendAudience.tutor
        tutor_facts = await build_tutor_facts(session, person, window)
        if not tutor_facts.classes:
            return None
        written = await _latest_narratives(
            session,
            person.organization_id,
            NarrativeAudience.tutor_class,
            [c.group_id for c in tutor_facts.classes],
            start,
        )
        paragraphs = [
            _paragraph(c.group_name, written[c.group_id])
            for c in tutor_facts.classes
            if c.group_id in written
        ]
        facts: TutorFacts | StudentFacts | ParentFacts = tutor_facts
    elif person.role == UserRole.student:
        audience = WeeklySendAudience.student
        student_facts = await build_student_facts(session, person, window)
        if not student_facts.classes:
            return None
        # No paragraph: the one stored narrative about a learner is written to
        # their parent, in the third person. A student gets the facts alone
        # until there is a paragraph written for them.
        facts = student_facts
    else:
        audience = WeeklySendAudience.parent
        parent_facts = await build_parent_facts(session, person, window)
        if not any(child.classes for child in parent_facts.children):
            return None
        children = (
            await session.execute(
                select(User.id, User.name)
                .join(ParentLink, ParentLink.student_id == User.id)
                .where(
                    ParentLink.parent_id == person.id,
                    User.organization_id == person.organization_id,
                )
                .order_by(User.id)
            )
        ).all()
        written = await _latest_narratives(
            session,
            person.organization_id,
            NarrativeAudience.parent_student,
            [c.id for c in children],
            start,
        )
        paragraphs = [_paragraph(c.name, written[c.id]) for c in children if c.id in written]
        facts = parent_facts

    send = WeeklySend(
        organization_id=person.organization_id,
        recipient_user_id=person.id,
        audience=audience,
        week_start=facts.window_start,
        week_end=facts.window_end,
        facts=dump_facts(audience, facts),
        paragraphs=paragraphs,
    )
    session.add(send)
    await session.flush()
    await notify(
        session,
        recipient=person,
        kind=NotificationKind.weekly_send,
        params=message_params(audience, facts),
        link_path=f"/weekly/{send.id}",
        # The week's end, not the row id: a rebuilt week must not message twice.
        idempotency_key=f"weekly_send:{person.id}:{facts.window_end.isoformat()}",
    )
    return send


async def _already_built(session: AsyncSession, organization_id: int, week_end: datetime) -> bool:
    return (
        await session.scalar(
            select(WeeklySend.id)
            .where(WeeklySend.organization_id == organization_id, WeeklySend.week_end == week_end)
            .limit(1)
        )
    ) is not None


async def build_weekly_sends(session: AsyncSession, payload: dict) -> None:
    """Job handler: store and announce one organization's week.

    Safe to re-run (`BE-6`): an organization whose week already has a row is
    skipped whole, and each reader's row is unique per week besides. The payload
    carries the organization and the moment the week closed (`BE-9`); the window
    is recomputed from the organization's current settings, and a send day
    changed in between simply makes this job a no-op — the sweep picks up the
    new moment when it comes.
    """
    if not get_settings().weekly_send_enabled:
        return
    org = await session.get(Organization, payload["organization_id"])
    if org is None:
        return
    week_end = datetime.fromisoformat(payload["week_end"])
    window = await organization_week_window(
        session, org.id, week_end, org.weekly_send_weekday, org.weekly_send_hour
    )
    if window[1] != week_end or await _already_built(session, org.id, week_end):
        return

    built = 0
    for person in await _recipients(session, org.id):
        try:
            async with session.begin_nested():
                if await _build_one(session, person, window) is not None:
                    built += 1
        except Exception:  # noqa: BLE001 - one reader must not cost the others their week
            log.exception("could not build the weekly send for user %s", person.id)
    log.info("weekly send for organization %s: %s readers", org.id, built)


# ---------------------------------------------------------------------- sweep


async def _pending(session: AsyncSession, job_type: str) -> list[dict]:
    # Compared in Python, not SQL: payload is a JSON column and Postgres' json
    # type has no equality operator (as in services/narrative.py).
    return list(
        (
            await session.scalars(
                select(Job.payload).where(
                    Job.type == job_type,
                    Job.status.in_([JobStatus.pending, JobStatus.running]),
                )
            )
        ).all()
    )


async def ensure_weekly_send_sweep_scheduled(session: AsyncSession) -> None:
    """Startup floor: schedule a sweep if none is waiting. Idempotent."""
    if await _pending(session, SWEEP_JOB):
        return
    await enqueue(session, SWEEP_JOB, {})


async def _commit_successor_sweep() -> None:
    """Queue the next sweep in its **own committed transaction**, before the
    work. The worker commits a handler's session only on success, so a successor
    enqueued on the handler's session would vanish with a failed run — and after
    MAX_ATTEMPTS nothing would ever send a weekly report again until a restart
    (`services/narrative.py` records the same failure and the same fix)."""
    async with async_session() as session:
        waiting = await session.scalar(
            select(Job.id).where(Job.type == SWEEP_JOB, Job.status == JobStatus.pending).limit(1)
        )
        if waiting is not None:
            return
        interval = get_settings().weekly_send_sweep_interval_minutes
        await enqueue(
            session,
            SWEEP_JOB,
            {},
            run_after=datetime.now(timezone.utc) + timedelta(minutes=interval),
        )
        await session.commit()


async def _refresh_narratives(session: AsyncSession, organization_id: int) -> None:
    """Ask the one writer to bring this organization's paragraphs up to date
    before the build reads them. Ordinary, non-forced jobs: each is a no-op when
    nothing was marked since its last paragraph, so a quiet week costs nothing."""
    if not get_settings().narrative_enabled:
        return
    waiting = await _pending(session, CLASS_NARRATIVE_JOB)
    groups_waiting = {p.get("group_id") for p in waiting}
    students_waiting = {p.get("student_id") for p in waiting}
    group_ids = (
        await session.scalars(select(Group.id).where(Group.organization_id == organization_id))
    ).all()
    student_ids = (
        await session.scalars(
            select(distinct(GroupMember.student_id))
            .join(Group, Group.id == GroupMember.group_id)
            .where(Group.organization_id == organization_id)
        )
    ).all()
    # One flush for the batch, not one per row (`PERF-1`).
    session.add_all(
        [
            Job(
                type=CLASS_NARRATIVE_JOB,
                payload={"audience": NarrativeAudience.tutor_class.value, "group_id": gid},
            )
            for gid in group_ids
            if gid not in groups_waiting
        ]
        + [
            Job(
                type=CLASS_NARRATIVE_JOB,
                payload={"audience": NarrativeAudience.parent_student.value, "student_id": sid},
            )
            for sid in student_ids
            if sid not in students_waiting
        ]
    )


async def due_organizations(session: AsyncSession, now: datetime) -> list[tuple[int, datetime]]:
    """(organization, week end) for every organization whose week has closed in
    the last day and has not been built."""
    due: list[tuple[int, datetime]] = []
    orgs = (await session.scalars(select(Organization).order_by(Organization.id))).all()
    for org in orgs:
        try:
            _start, end = await organization_week_window(
                session, org.id, now, org.weekly_send_weekday, org.weekly_send_hour
            )
        except ValueError:
            log.exception("organization %s has an unusable weekly send setting", org.id)
            continue
        if now - end > LATE_GRACE or await _already_built(session, org.id, end):
            continue
        due.append((org.id, end))
    return due


async def sweep_weekly_sends(session: AsyncSession, payload: dict) -> None:
    """Job handler. Finds the organizations whose week has just closed, asks the
    narrative writer to refresh for them, and queues each one's build a few
    minutes out so those paragraphs exist when it runs."""
    await _commit_successor_sweep()
    settings = get_settings()
    # The schedule above is already re-armed, so switching this back on resumes
    # without a restart.
    if not settings.weekly_send_enabled:
        return
    now = datetime.now(timezone.utc)
    queued = {
        (p.get("organization_id"), p.get("week_end")) for p in await _pending(session, BUILD_JOB)
    }
    for organization_id, week_end in await due_organizations(session, now):
        if (organization_id, week_end.isoformat()) in queued:
            continue
        await _refresh_narratives(session, organization_id)
        await enqueue(
            session,
            BUILD_JOB,
            {"organization_id": organization_id, "week_end": week_end.isoformat()},
            run_after=now + timedelta(minutes=settings.weekly_send_narrative_lead_minutes),
        )


# ----------------------------------------------------------------------- read


async def latest_send(session: AsyncSession, user: User) -> WeeklySend | None:
    return await session.scalar(
        select(WeeklySend)
        .where(
            WeeklySend.recipient_user_id == user.id,
            WeeklySend.organization_id == user.organization_id,
        )
        .order_by(WeeklySend.week_end.desc(), WeeklySend.id.desc())
        .limit(1)
    )


async def sends_for(
    session: AsyncSession, organization_id: int, user_ids: Sequence[int], limit: int = 26
) -> list[WeeklySend]:
    """Newest first. Half a year by default: enough for "earlier reports"
    without the list growing for ever."""
    if not user_ids:
        return []
    return list(
        await session.scalars(
            select(WeeklySend)
            .where(
                WeeklySend.organization_id == organization_id,
                WeeklySend.recipient_user_id.in_(user_ids),
            )
            .order_by(WeeklySend.week_end.desc(), WeeklySend.id.desc())
            .limit(limit)
        )
    )
