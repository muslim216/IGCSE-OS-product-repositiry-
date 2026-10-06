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
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
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
from app.models.base import utcnow
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

#: A candidate week end is not due if the organization already sent a week that
#: closed within this long before it. Idempotency is per (organization, week
#: end), so a tutor moving the send hour or day just after a send would
#: otherwise produce a second end inside the grace window with no row of its
#: own, and everyone would be messaged twice for one week. After a change of
#: day, a candidate that would repeat more than half of the week already sent
#: is skipped (the next one is a week later, leaving a gap of at most 3.5
#: days); one that would repeat less than half is sent (an overlap of at most
#: 3.5 days). Neither can be avoided when the day moves, and half a week bounds
#: both.
OVERLAP = timedelta(days=3, hours=12)

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


def _paragraph(about: str, narrative: Narrative, child_id: int | None = None) -> dict:
    # `child_id` only on a parent send, where the paragraph is about one child.
    out = {"about": about, "text": narrative.text, "narrative_id": narrative.id}
    if child_id is not None:
        out["child_id"] = child_id
    return out


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
        .where(Group.organization_id == organization_id, Group.deleted_at.is_(None))
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
        paragraphs = [_paragraph(c.name, written[c.id], c.id) for c in children if c.id in written]
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
    try:
        # Its own savepoint: the stored send is the artifact, and the message
        # only points at it. A failure to queue the message must not undo the
        # send the reader's home page links to.
        async with session.begin_nested():
            await notify(
                session,
                recipient=person,
                kind=NotificationKind.weekly_send,
                params=message_params(audience, facts),
                link_path=f"/weekly/{send.id}",
                # The week's end, not the row id: a rebuilt week must not
                # message twice.
                idempotency_key=f"weekly_send:{person.id}:{facts.window_end.isoformat()}",
            )
    except Exception:  # noqa: BLE001 - see above
        log.exception(
            "stored the weekly send for user %s but could not queue its message", person.id
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


async def _sent_recently(session: AsyncSession, organization_id: int, week_end: datetime) -> bool:
    """True when a stored send closed later than `week_end - OVERLAP` — the same
    week sent under a send moment the tutor has since changed."""
    return (
        await session.scalar(
            select(WeeklySend.id)
            .where(
                WeeklySend.organization_id == organization_id,
                WeeklySend.week_end > week_end - OVERLAP,
            )
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


async def _builds_handled(session: AsyncSession) -> set[tuple[int, str]]:
    """(organization, week end) for every build that is waiting, running or has
    finished. A finished build counts even though it may have stored nothing:
    an account with no classes has no rows to show for its week, and without
    this the sweep would queue it again every cycle until the grace ran out. A
    *failed* build is left out on purpose, so the next sweep tries it again.
    """
    # Bounded by when the job row was written, on the same clock that wrote it:
    # a build older than the grace can only be for a week no longer due.
    payloads = await session.scalars(
        select(Job.payload).where(
            Job.type == BUILD_JOB,
            Job.status != JobStatus.failed,
            Job.created_at >= utcnow() - LATE_GRACE - timedelta(days=1),
        )
    )
    return {(p.get("organization_id"), p.get("week_end")) for p in payloads}


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
        await session.scalars(
            select(Group.id).where(
                Group.organization_id == organization_id, Group.deleted_at.is_(None)
            )
        )
    ).all()
    student_ids = (
        await session.scalars(
            select(distinct(GroupMember.student_id))
            .join(Group, Group.id == GroupMember.group_id)
            .where(Group.organization_id == organization_id, Group.deleted_at.is_(None))
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
        if now - end > LATE_GRACE or await _sent_recently(session, org.id, end):
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
    queued = await _builds_handled(session)
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


@dataclass(frozen=True)
class SendView:
    """A stored send as one particular reader may see it. The row itself is
    never edited: what a reader may see is decided at read time, because the
    parent's links and the tutor's classes change after a send is stored."""

    send: WeeklySend
    facts: TutorFacts | StudentFacts | ParentFacts
    paragraphs: list[dict]


@dataclass(frozen=True)
class LinkedChild:
    id: int
    name: str
    linked_at: datetime


async def linked_children(
    session: AsyncSession, parent_id: int, organization_id: int, *, taught_by: int | None = None
) -> list[LinkedChild]:
    """The children this parent is linked to *now*, optionally only those
    `taught_by` that tutor teaches."""
    query = (
        select(User.id, User.name, ParentLink.created_at)
        .join(ParentLink, ParentLink.student_id == User.id)
        .where(
            ParentLink.parent_id == parent_id,
            User.organization_id == organization_id,
            User.role == UserRole.student,
        )
    )
    if taught_by is not None:
        query = query.where(
            User.id.in_(
                select(GroupMember.student_id)
                .join(Group, Group.id == GroupMember.group_id)
                .where(Group.tutor_id == taught_by, Group.organization_id == organization_id)
            )
        )
    return [LinkedChild(i, n, _aware(at)) for i, n, at in (await session.execute(query)).all()]


def restrict_to_children(
    send: WeeklySend, allowed: Sequence[LinkedChild], *, hide_dropped: bool = False
) -> SendView | None:
    """The send as a reader who may see only `allowed` children sees it, or None
    when nothing is left.

    A stored child with an id is kept only if that id is allowed: identity, so a
    different child who shares a name (linked after the first was unlinked)
    inherits nothing. A child stored before ids existed has only a name, so it
    falls back to name matching, with two guards: only links made before the
    send was stored count (a later link cannot inherit it), and a name stored
    more often than it is allowed drops all its copies (fail closed). Each
    paragraph is attributed by its `child_id`, or by `about` when it predates one.

    `hide_dropped` zeroes `dropped_links`, a count of the parent's links that did
    not resolve to a child when the send was built: it says nothing a tutor needs
    about a family's other links.
    """
    facts = load_facts(send.audience, send.facts)
    if not isinstance(facts, ParentFacts):
        return SendView(send, facts, list(send.paragraphs))
    allowed_ids = {c.id for c in allowed}
    stored_at = _aware(send.created_at)
    legacy_allowed = Counter(c.name for c in allowed if c.linked_at <= stored_at)
    legacy_stored = Counter(c.child_name for c in facts.children if c.child_id is None)
    legacy_kept = {name for name, n in legacy_stored.items() if legacy_allowed[name] >= n}
    children = tuple(
        c
        for c in facts.children
        if (c.child_id in allowed_ids if c.child_id is not None else c.child_name in legacy_kept)
    )
    if not children:
        return None
    kept_ids = {c.child_id for c in children if c.child_id is not None}
    if len(children) == len(facts.children) and not hide_dropped:
        return SendView(send, facts, list(send.paragraphs))
    return SendView(
        send,
        replace(
            facts,
            children=children,
            dropped_links=0 if hide_dropped else facts.dropped_links,
        ),
        [
            p
            for p in send.paragraphs
            if (
                p["child_id"] in kept_ids
                if p.get("child_id") is not None
                else p["about"] in legacy_kept
            )
        ],
    )


async def view_for_reader(
    session: AsyncSession,
    reader: User,
    send: WeeklySend,
    *,
    allowed: Sequence[LinkedChild] | None = None,
) -> SendView | None:
    """What `reader` may see of a send they are already permitted to open.

    A parent reading their own send sees only children still linked to them. A
    tutor reading a parent's send sees only the children they teach (and who are
    still linked). An admin keeps the organization-wide view the rest of this
    feature gives them. `allowed` lets a list pass one lookup for many sends.
    """
    if send.audience != WeeklySendAudience.parent or reader.role == UserRole.admin:
        return SendView(send, load_facts(send.audience, send.facts), list(send.paragraphs))
    others = reader.id != send.recipient_user_id
    if allowed is None:
        allowed = await linked_children(
            session,
            send.recipient_user_id,
            send.organization_id,
            taught_by=reader.id if others else None,
        )
    return restrict_to_children(send, allowed, hide_dropped=others)
