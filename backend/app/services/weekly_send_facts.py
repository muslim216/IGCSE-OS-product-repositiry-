"""The facts behind the weekly send (task 8.2, AV-49, AV-50, AV-62 to AV-66).

The weekly send is "fixed facts plus one AI paragraph". This module is the facts:
computed deterministically from rows, with no model anywhere (`PROD-6`). The
paragraph written later may only steer; it must never restate a number these
facts do not contain.

Three variants, one per recipient:

- **Tutor**: leads with each class's position on the teaching plan ("everything
  revolves around the teaching plan"), then readiness, attendance, homework and
  the review queue. Punctuality appears here and nowhere else (AV-32).
- **Student**: their own week, with the chapter the class is on and the next one.
- **Parent**: *is* the parent report (AV-63): readiness and predicted grade,
  attendance and homework record, and the chapter the class is on. Never the
  topic breakdown and never mistake patterns (AV-64).

**What "punctuality" is.** The register has two states, present and absent, by the
owner's decision (no "late"), so lateness cannot be about attendance. The only
timed commitment a learner makes is a homework deadline: punctuality is how many
of this week's hand-ins arrived after the assignment's `due_at`. An assignment
with no due date can never be late and is not counted either way (`PROD-2`).

**F9 (threat review): nothing here is free text from a student.** A fact is a
number, a date, a state, or a name someone with authority over the account typed
(class, subject, chapter, the learner's own account name). The types below are
frozen dataclasses whose only `str` fields are those names and enumerable
statuses; there is no field a feedback sentence, a mistake note, a typed answer
or the AI's marking reasoning could be put in, and the fact queries never select
those columns. `tests/test_weekly_send_facts.py` scans the produced objects for
that, so a future field that breaks it fails a test rather than a review.

Missing is absent: every figure that can be missing is `None`, never `0`
(`PROD-2`). Only finalized outcomes count (`PROD-5`, `SETTLED_STATUSES`).
Everything is scoped by the authenticated user's organization (`SEC-7`). Queries
are grouped, never one per learner, lesson or assignment: the tutor path issues a
fixed set for the whole account plus a small constant number *per class* (the
shared verdict loader, `class_verdicts`, is per class). A query-count test pins
both properties. The student and parent paths build the verdict for that learner
alone, but the snapshot ranking still reads the class's members in SQL.

Boundaries and the weak-topic threshold are read as of now, not as of the window's
end: they are the tutor's current settings, and a send fires at the window's end.
Snapshots are the exception and are read as of the window end.
"""

import logging
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    SETTLED_STATUSES,
    AssessableWork,
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    AttendanceState,
    Group,
    GroupMember,
    Lesson,
    LessonAttendance,
    Organization,
    ParentLink,
    PlanSlot,
    QuestionTopic,
    Submission,
    SubmissionStatus,
    TeachingPlan,
    TeachingPlanStatus,
    Topic,
    User,
    UserRole,
    WorkKind,
)
from app.schemas.readiness import VerdictStatus
from app.services.attendance import counts_for_attendance, in_zone
from app.services.class_readiness import LearnerSnapshot, latest_learner_snapshots
from app.services.class_verdicts import class_verdicts
from app.services.plan_progress import class_progress
from app.services.readiness_shared import trend_direction
from app.services.student_verdict import Verdict
from app.services.timezones import is_valid_timezone
from app.services.today import pending_review_count, tutor_groups
from app.services.today_overview import SlotRow, _slot_rows, _slot_select, missing_handins

logger = logging.getLogger(__name__)

Direction = Literal["up", "flat", "down"]

#: Days between the two ends of "readiness since last week".
COMPARISON_DAYS = 7
#: Weak topics named per class on the tutor's page.
TOPICS_SHOWN = 3

WEEK = timedelta(days=7)


# ---------------------------------------------------------------- the window


def week_window(
    now_utc: datetime, tz_name: str | None, weekday: int, hour: int
) -> tuple[datetime, datetime]:
    """The seven days ending at the most recent send moment, as (start, end) in
    UTC with `start <= t < end`.

    The send moment is `weekday` (Monday=0) at `hour`:00 on **the tutor's
    organization's clock**, never the recipient's. AV-90: the send follows the
    tutor's clock, so a parent in another zone and a student abroad get it at the
    same instant as the tutor, and every recipient's facts describe the same
    window. A per-recipient clock would give a family and their tutor different
    "weeks" for the same Sunday.

    A moment exactly at the send time is the *end* of the window that is closing
    now, so the send that fires at that instant covers the week just finished.
    The seven days are seven local days, not 168 hours: across a clock change the
    window is an hour shorter or longer, because "a week ending Sunday 18:00" is
    what the tutor means. `None` or an unknown zone is UTC, as everywhere else.
    """
    if not 0 <= weekday <= 6:
        raise ValueError("weekday must be 0 (Monday) to 6 (Sunday)")
    if not 0 <= hour <= 23:
        raise ValueError("hour must be 0 to 23")
    if tz_name and not is_valid_timezone(tz_name):
        logger.warning("time zone %r cannot be loaded; the weekly window uses UTC", tz_name)
    moment = _utc(now_utc)
    zone = ZoneInfo(tz_name) if tz_name and is_valid_timezone(tz_name) else timezone.utc
    local_now = moment.astimezone(zone)
    # Both ends come from the same wall-clock formula, so one window's end is
    # exactly the next one's start and consecutive weeks tile with no gap or
    # overlap across a clock change. A send hour that does not exist on a
    # spring-forward day resolves to the real instant the zone gives it. The
    # comparison with "now" is in UTC.
    end_date = local_now.date() - timedelta(days=(local_now.weekday() - weekday) % 7)
    end = _send_moment(end_date, hour, zone)
    if end > moment:
        end_date -= WEEK
        end = _send_moment(end_date, hour, zone)
    return _send_moment(end_date - WEEK, hour, zone), end


def _send_moment(day: date, hour: int, zone: tzinfo) -> datetime:
    """The UTC instant of `hour`:00 on `day` in `zone`."""
    return datetime.combine(day, time(hour)).replace(tzinfo=zone).astimezone(timezone.utc)


Window = tuple[datetime, datetime]


@dataclass(frozen=True)
class _Clock:
    """The window on the organization's clock: what every "this week" date test
    below is made against."""

    start: datetime  # UTC
    end: datetime  # UTC
    zone: str | None
    start_local: datetime
    end_local: datetime

    @property
    def today(self) -> date:
        return self.end_local.date()

    def contains(self, day: date, start_time: time | None) -> bool:
        """Whether a lesson or slot on `day` belongs to this window. With a start
        time it is placed exactly; without one (unknown, never midnight, `DB-9`)
        the week owns the days after the opening day up to and including the
        closing day, so consecutive windows never both claim one."""
        if start_time is None:
            return self.start_local.date() < day <= self.end_local.date()
        placed = datetime.combine(day, start_time)
        return self.start_local.replace(tzinfo=None) <= placed < self.end_local.replace(tzinfo=None)

    def is_after(self, day: date, start_time: time | None) -> bool:
        """The mirror of `contains` for "later than this window": the same
        placement rule, so a slot dated today but timed after the send hour is in
        the *next* week, not in neither."""
        if start_time is None:
            return day > self.end_local.date()
        return datetime.combine(day, start_time) >= self.end_local.replace(tzinfo=None)

    def holds(self, moment: datetime) -> bool:
        return self.start <= _utc(moment) < self.end


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


async def _clock(session: AsyncSession, organization_id: int, window: Window) -> _Clock:
    org = await session.get(Organization, organization_id)
    if org is None:
        raise ValueError(f"organization {organization_id} not found")
    zone = _org_zone(org)
    start, end = _utc(window[0]), _utc(window[1])
    return _Clock(start, end, zone, in_zone(start, zone), in_zone(end, zone))


def _org_zone(org: Organization) -> str | None:
    """The organization's zone, or None (UTC) when unset or unloadable. The one
    place a zone is read for both the window and the clock, so they cannot
    disagree; an unloadable non-empty value is logged, not silent."""
    name = (org.timezone or "").strip()
    if not name:
        return None
    if not is_valid_timezone(name):
        logger.warning("organization %s time zone %r cannot be loaded; using UTC", org.id, name)
        return None
    return name


async def organization_week_window(
    session: AsyncSession, organization_id: int, now_utc: datetime, weekday: int, hour: int
) -> Window:
    """`week_window` on the organization's own clock (AV-90), read through the
    same zone resolution the facts use."""
    org = await session.get(Organization, organization_id)
    if org is None:
        raise ValueError(f"organization {organization_id} not found")
    return week_window(now_utc, _org_zone(org), weekday, hour)


# ------------------------------------------------------------------ fact types


@dataclass(frozen=True)
class ChapterRef:
    code: str
    title: str


@dataclass(frozen=True)
class AttendanceFacts:
    """Lessons in the window and the register's two states. `not_taken` is a
    lesson nobody marked, never an absence (`PROD-2`)."""

    lessons_held: int
    present: int
    absent: int
    not_taken: int
    #: present / (present + absent); None when nothing was marked.
    rate: float | None


@dataclass(frozen=True)
class HomeworkFacts:
    #: Assignments *created* in the window (and published now). There is no
    #: published-at column yet, so creation stands in for "set"; an approximation
    #: until one exists.
    set_count: int
    #: Hand-ins that arrived in the window.
    handed_in_count: int
    #: Hand-ins overdue at the end of the window (the Overview's rule, shared).
    missing_count: int


@dataclass(frozen=True)
class Punctuality:
    """Tutor variant only. Hand-ins in the window against their own deadline."""

    on_time: int
    late: int


@dataclass(frozen=True)
class MarkedFacts:
    marked: int
    auto_finalized: int


@dataclass(frozen=True)
class TopicCount:
    #: A syllabus topic title, never a student's words.
    title: str
    learners: int


@dataclass(frozen=True)
class VerdictCount:
    status: VerdictStatus
    learners: int


@dataclass(frozen=True)
class PlanFacts:
    """Where a class stands on its accepted plan. Absent when it has none."""

    this_week_chapter: ChapterRef | None
    next_chapter: ChapterRef | None
    #: Whether any published homework carries a question on the next chapter.
    #: None when there is no next chapter to ask about.
    next_chapter_homework_set: bool | None
    lessons_planned_this_week: int
    lessons_taught_this_week: int
    #: Planned lessons dated before the window's end with none recorded
    #: (`plan_progress`). None when that read has no entry for the class (it has
    #: not reached its first planned lesson): not knowing is not "0 behind".
    lessons_behind: int | None
    #: Lessons already taught ahead of their date.
    lessons_ahead: int
    weeks_to_exam: int | None


@dataclass(frozen=True)
class TutorClassFacts:
    group_id: int
    group_name: str
    subject_name: str | None
    plan: PlanFacts | None
    verdicts: tuple[VerdictCount, ...]
    readiness_direction: Direction | None
    readiness_compared_count: int
    weak_topics: tuple[TopicCount, ...]
    attendance: AttendanceFacts | None
    homework: HomeworkFacts | None
    punctuality: Punctuality | None


@dataclass(frozen=True)
class TutorFacts:
    window_start: datetime
    window_end: datetime
    classes: tuple[TutorClassFacts, ...]
    review_queue: int
    marked: MarkedFacts | None


@dataclass(frozen=True)
class StudentClassFacts:
    group_id: int
    group_name: str
    subject_name: str | None
    verdict: VerdictStatus
    readiness_score: float | None
    predicted_grade: str | None
    readiness_direction: Direction | None
    #: Titles of the weakest topics named by the shared verdict.
    weak_topics: tuple[str, ...]
    this_week_chapter: ChapterRef | None
    next_chapter: ChapterRef | None
    attendance: AttendanceFacts | None
    homework: HomeworkFacts | None


@dataclass(frozen=True)
class StudentFacts:
    window_start: datetime
    window_end: datetime
    student_name: str
    classes: tuple[StudentClassFacts, ...]
    marked: MarkedFacts | None


@dataclass(frozen=True)
class ParentClassFacts:
    """No topic list and no mistakes: the parent report is readiness, grade,
    attendance and homework (AV-64). The chapter is a name, not a breakdown."""

    group_name: str
    subject_name: str | None
    verdict: VerdictStatus
    readiness_score: float | None
    predicted_grade: str | None
    readiness_direction: Direction | None
    chapter: ChapterRef | None
    attendance: AttendanceFacts | None
    homework: HomeworkFacts | None


@dataclass(frozen=True)
class ParentChildFacts:
    child_name: str
    classes: tuple[ParentClassFacts, ...]
    #: Who the block is about. A name is not an identity: a different child
    #: with the same name, linked later, must not inherit this block when it
    #: is read back. None on sends stored before the field existed.
    child_id: int | None = None


@dataclass(frozen=True)
class ParentFacts:
    window_start: datetime
    window_end: datetime
    children: tuple[ParentChildFacts, ...]
    #: Parent links that did not become a block (the child is in another
    #: organization or no longer a student). Logged too; a send never fails on one.
    dropped_links: int


# ------------------------------------------------------------------- shared reads


async def _joined(
    session: AsyncSession, group_ids: Sequence[int], only_student: int | None = None
) -> dict[int, dict[int, datetime]]:
    """{group: {student: joined_at (UTC)}}. `GroupMember.created_at` is the join
    moment, the same proxy the Overview uses for "not their homework"."""
    query = select(GroupMember.group_id, GroupMember.student_id, GroupMember.created_at).where(
        GroupMember.group_id.in_(list(group_ids))
    )
    if only_student is not None:
        query = query.where(GroupMember.student_id == only_student)
    out: dict[int, dict[int, datetime]] = defaultdict(dict)
    for gid, sid, joined in (await session.execute(query)).all():
        out[gid][sid] = _utc(joined)
    return out


async def _attendance(
    session: AsyncSession,
    organization_id: int,
    group_ids: Sequence[int],
    joined: dict[int, dict[int, datetime]],
    clock: _Clock,
    only_student: int | None = None,
) -> dict[int, AttendanceFacts]:
    """Per class, over the lessons in the window, by the one shared definition
    (`counts_for_attendance`) read at the window's end. A class with no lesson
    that counted is absent from the result; `lessons_held` is the filtered count."""
    lessons = [
        lesson
        for lesson in (
            await session.scalars(
                select(Lesson).where(
                    Lesson.organization_id == organization_id,
                    Lesson.group_id.in_(list(group_ids)),
                    Lesson.date.between(clock.start_local.date(), clock.today),
                )
            )
        ).all()
        if clock.contains(lesson.date, lesson.start_time)
    ]
    if not lessons:
        return {}
    marks: dict[int, dict[int, AttendanceState]] = defaultdict(dict)
    mark_query = select(
        LessonAttendance.lesson_id, LessonAttendance.student_id, LessonAttendance.state
    ).where(
        LessonAttendance.lesson_id.in_([lesson.id for lesson in lessons]),
        LessonAttendance.organization_id == organization_id,
    )
    if only_student is not None:
        mark_query = mark_query.where(LessonAttendance.student_id == only_student)
    for lid, sid, state in (await session.execute(mark_query)).all():
        marks[lid][sid] = state

    tally: Counter[tuple[str, int]] = Counter()
    held: Counter[int] = Counter()
    for lesson in lessons:
        counted = False
        roster = joined.get(lesson.group_id, {})
        # Everyone enrolled plus anyone with a mark who has since left.
        for sid in set(roster) | set(marks[lesson.id]):
            state = marks[lesson.id].get(sid)
            joined_on = in_zone(roster[sid], clock.zone).date() if sid in roster else None
            if not counts_for_attendance(lesson, state, joined_on, clock.today, clock.end_local):
                continue
            counted = True
            tally["not_taken" if state is None else state.value, lesson.group_id] += 1
        # A lesson is "held" for this reader only if something about it counted:
        # one later today that has not ended, or held before the learner joined,
        # is not yet a lesson to report (the same filter as the figures).
        if counted:
            held[lesson.group_id] += 1
    out: dict[int, AttendanceFacts] = {}
    for gid, lessons_held in held.items():
        present = tally["present", gid]
        absent = tally["absent", gid]
        out[gid] = AttendanceFacts(
            lessons_held=lessons_held,
            present=present,
            absent=absent,
            not_taken=tally["not_taken", gid],
            rate=present / (present + absent) if present + absent else None,
        )
    return out


async def _homework(
    session: AsyncSession,
    organization_id: int,
    group_ids: Sequence[int],
    joined: dict[int, dict[int, datetime]],
    clock: _Clock,
    only_student: int | None = None,
) -> tuple[dict[int, HomeworkFacts], dict[int, Punctuality]]:
    """Per class: what was set, handed in and is missing, plus on-time against
    late. A class with no published assignment has neither (nothing to report,
    never "0 set")."""
    published = (
        await session.execute(
            select(
                Assignment.group_id, Assignment.work_id, Assignment.due_at, Assignment.created_at
            )
            .join(Group, Group.id == Assignment.group_id)
            .where(
                Group.organization_id == organization_id,
                Assignment.group_id.in_(list(group_ids)),
                Assignment.status == AssignmentStatus.published,
            )
        )
    ).all()
    if not published:
        return {}, {}
    sub_query = select(Submission.work_id, Submission.student_id, Submission.submitted_at).where(
        Submission.work_id.in_([work_id for _g, work_id, _d, _c in published])
    )
    if only_student is not None:
        sub_query = sub_query.where(Submission.student_id == only_student)
    handed: dict[int, set[int]] = defaultdict(set)
    arrivals: dict[int, list[datetime]] = defaultdict(list)
    for work_id, sid, at in (await session.execute(sub_query)).all():
        # As at the window's end: a hand-in after it is next week's fact, and the
        # student was still missing it when this one was written.
        if _utc(at) >= clock.end:
            continue
        handed[work_id].add(sid)
        arrivals[work_id].append(_utc(at))

    set_n: Counter[int] = Counter()
    in_n: Counter[int] = Counter()
    missing: Counter[int] = Counter()
    on_time: Counter[int] = Counter()
    late: Counter[int] = Counter()
    for gid, work_id, due_at, created_at in published:
        if _utc(created_at) >= clock.end:
            continue  # set after this window closed
        if clock.holds(created_at):
            set_n[gid] += 1
        missing[gid] += missing_handins(joined.get(gid, {}), handed[work_id], due_at, clock.end)
        for at in arrivals[work_id]:
            if not clock.holds(at):
                continue
            in_n[gid] += 1
            if due_at is not None:
                (late if at > _utc(due_at) else on_time)[gid] += 1
    gids = {g for g, _w, _d, created in published if _utc(created) < clock.end}
    return (
        {g: HomeworkFacts(set_n[g], in_n[g], missing[g]) for g in gids},
        {g: Punctuality(on_time[g], late[g]) for g in gids if on_time[g] + late[g]},
    )


async def _marked(
    session: AsyncSession,
    organization_id: int,
    student_ids: Sequence[int],
    clock: _Clock,
    group_ids: Sequence[int] | None = None,
) -> MarkedFacts | None:
    """Pieces whose marks settled in the window (`SETTLED_STATUSES`, `PROD-5`).
    Both a tutor sign-off and the auto-finalize job stamp `finalized_at`
    (`marking.py`), so that is the settle moment; `submitted_at` is only the
    fallback for older rows that never had one. None when nothing settled.

    `group_ids` scopes the tutor's count: homework set in the tutor's own classes,
    plus past papers and mocks by students on their rosters. Those two kinds have
    no class, and the rest of the app (review queue, activity) attributes them by
    the student's organization, so attributing them by roster is the narrowest
    honest reading. A student's own count passes no groups."""
    if not student_ids:
        return None
    settled_at = func.coalesce(Submission.finalized_at, Submission.submitted_at)
    query = (
        select(Submission.status, func.count(Submission.id))
        .join(AssessableWork, AssessableWork.id == Submission.work_id)
        .where(
            AssessableWork.organization_id == organization_id,
            Submission.student_id.in_(list(student_ids)),
            Submission.status.in_(SETTLED_STATUSES),
            settled_at >= clock.start,
            settled_at < clock.end,
        )
        .group_by(Submission.status)
    )
    if group_ids is not None:
        query = query.outerjoin(Assignment, Assignment.work_id == Submission.work_id).where(
            or_(Assignment.group_id.in_(list(group_ids)), AssessableWork.kind != WorkKind.homework)
        )
    rows = (await session.execute(query)).all()
    total = sum(n for _s, n in rows)
    if not total:
        return None
    return MarkedFacts(
        marked=total,
        auto_finalized=sum(n for s, n in rows if s == SubmissionStatus.auto_finalized),
    )


@dataclass(frozen=True)
class _Chapters:
    this_week: ChapterRef | None
    next: ChapterRef | None
    #: The next chapter's id, for the homework lookup (codes repeat across subjects).
    next_id: int | None
    planned: int
    taught: int
    ahead: int


async def _plan_slots(
    session: AsyncSession, organization_id: int, group_ids: Sequence[int]
) -> tuple[dict[int, list[SlotRow]], dict[int, date]]:
    """Live slots of each class's accepted plan, in teaching order, and its exam
    date. A draft is never read (task 6.4)."""
    rows = _slot_rows(
        (
            await session.execute(
                _slot_select()
                .where(
                    TeachingPlan.organization_id == organization_id,
                    TeachingPlan.group_id.in_(list(group_ids)),
                    TeachingPlan.status == TeachingPlanStatus.accepted,
                    PlanSlot.cancelled_at.is_(None),
                )
                .order_by(PlanSlot.scheduled_date, PlanSlot.sequence, PlanSlot.id)
            )
        ).all()
    )
    slots: dict[int, list[SlotRow]] = defaultdict(list)
    for slot in rows:
        slots[slot.group_id].append(slot)
    exams: dict[int, date] = dict(
        (
            await session.execute(
                select(TeachingPlan.group_id, TeachingPlan.exam_date).where(
                    TeachingPlan.organization_id == organization_id,
                    TeachingPlan.group_id.in_(list(group_ids)),
                    TeachingPlan.status == TeachingPlanStatus.accepted,
                )
            )
        )
        .tuples()
        .all()
    )
    # A class with an accepted plan but every slot cancelled still has a plan.
    for gid in exams:
        slots.setdefault(gid, [])
    return slots, exams


def _chapters(slots: list[SlotRow], clock: _Clock) -> _Chapters:
    """This week's chapter is the one of the first lesson planned in the window;
    the next is the first chapter *after* the window that differs from it."""
    in_week = [s for s in slots if clock.contains(s.scheduled_date, s.start_time)]
    after = [s for s in slots if clock.is_after(s.scheduled_date, s.start_time)]

    def ref(slot: SlotRow) -> ChapterRef:
        return ChapterRef(slot.chapter_code, slot.chapter_title)

    this_week = ref(in_week[0]) if in_week else None
    following = next((s for s in after if ref(s) != this_week), None)
    return _Chapters(
        this_week=this_week,
        next=ref(following) if following else None,
        next_id=following.chapter_id if following else None,
        planned=len(in_week),
        taught=sum(1 for s in in_week if s.lesson_id is not None or s.started),
        ahead=sum(1 for s in after if s.lesson_id is not None or s.started),
    )


async def _homework_chapters(
    session: AsyncSession, organization_id: int, group_ids: Sequence[int]
) -> set[tuple[int, int]]:
    """(group, chapter id) pairs that published homework has a question on."""
    rows = await session.execute(
        select(Assignment.group_id, Topic.chapter_id)
        .join(AssignmentQuestion, AssignmentQuestion.assignment_id == Assignment.id)
        .join(QuestionTopic, QuestionTopic.question_id == AssignmentQuestion.id)
        .join(Topic, Topic.id == QuestionTopic.topic_id)
        .where(
            Group.id == Assignment.group_id,
            Group.organization_id == organization_id,
            Assignment.group_id.in_(list(group_ids)),
            Assignment.status == AssignmentStatus.published,
            Topic.chapter_id.is_not(None),
        )
        .distinct()
    )
    return {(gid, cid) for gid, cid in rows.all()}


@dataclass(frozen=True)
class _Readiness:
    verdicts: dict[int, Verdict]
    now: dict[int, LearnerSnapshot]
    then: dict[int, LearnerSnapshot]


async def _readiness(
    session: AsyncSession,
    groups: Sequence[Group],
    clock: _Clock,
    only_student: int | None = None,
) -> dict[int, _Readiness]:
    """Each class's learners as at the window's end, and a week before it. Both
    ends use `latest_learner_snapshots`, and the verdict is the shared
    `class_verdicts` read from the same snapshots, so no role can be told a
    different story from another (the coherence pass)."""
    group_ids = [g.id for g in groups]
    now = await latest_learner_snapshots(session, group_ids, before=clock.end)
    then = await latest_learner_snapshots(
        session, group_ids, before=clock.end - timedelta(days=COMPARISON_DAYS)
    )
    if only_student is not None:
        # One learner's verdict needs only their own run's factor rows: narrowing
        # the snapshots first keeps the loader from reading the whole class's.
        now = {gid: {s: v for s, v in per.items() if s == only_student} for gid, per in now.items()}
        then = {
            gid: {s: v for s, v in per.items() if s == only_student} for gid, per in then.items()
        }
    return {
        g.id: _Readiness(
            verdicts=await class_verdicts(session, g, now[g.id]),
            now=now[g.id],
            then=then[g.id],
        )
        for g in groups
    }


def _direction(pairs: list[tuple[float, float]]) -> Direction | None:
    """Mean score then against now over the learners who have both ends. The same
    run at both ends is not a week of history and is left out."""
    if not pairs:
        return None
    return cast(
        Direction | None,
        trend_direction(
            [sum(o for o, _ in pairs) / len(pairs), sum(n for _, n in pairs) / len(pairs)]
        ),
    )


def _pairs(r: _Readiness, students: Sequence[int]) -> list[tuple[float, float]]:
    out = []
    for sid in students:
        new, old = r.now.get(sid), r.then.get(sid)
        if new is None or old is None or new.score is None or old.score is None:
            continue
        if new.evaluation_run_id != old.evaluation_run_id:
            out.append((old.score, new.score))
    return out


# --------------------------------------------------------------------- tutor


async def build_tutor_facts(session: AsyncSession, tutor: User, window: Window) -> TutorFacts:
    if tutor.role not in (UserRole.tutor, UserRole.admin):
        raise ValueError("tutor facts are built for a tutor account")
    oid = tutor.organization_id
    clock = await _clock(session, oid, window)
    groups = [g for g in await tutor_groups(session, tutor.id) if g.organization_id == oid]
    queue = await pending_review_count(session, oid)
    if not groups:
        return TutorFacts(clock.start, clock.end, (), queue, None)
    group_ids = [g.id for g in groups]

    joined = await _joined(session, group_ids)
    attendance = await _attendance(session, oid, group_ids, joined, clock)
    homework, punctuality = await _homework(session, oid, group_ids, joined, clock)
    readiness = await _readiness(session, groups, clock)
    slots, exams = await _plan_slots(session, oid, group_ids)
    with_homework = await _homework_chapters(session, oid, list(exams))
    progress = await class_progress(session, tutor, clock.today, now=clock.end)

    classes: list[TutorClassFacts] = []
    for g in groups:
        plan = None
        if g.id in exams:
            ch = _chapters(slots[g.id], clock)
            prog = progress.get(g.id)
            days_left = (exams[g.id] - clock.today).days
            plan = PlanFacts(
                this_week_chapter=ch.this_week,
                next_chapter=ch.next,
                next_chapter_homework_set=(
                    None if ch.next_id is None else (g.id, ch.next_id) in with_homework
                ),
                lessons_planned_this_week=ch.planned,
                lessons_taught_this_week=ch.taught,
                lessons_behind=prog[1].missed if prog else None,
                lessons_ahead=ch.ahead,
                weeks_to_exam=-(-days_left // 7) if days_left >= 0 else None,
            )
        r = readiness[g.id]
        pairs = _pairs(r, list(r.verdicts))
        weak = Counter(t for v in r.verdicts.values() for t in v.reason_topics)
        classes.append(
            TutorClassFacts(
                group_id=g.id,
                group_name=g.name,
                subject_name=g.subject.name if g.subject else None,
                plan=plan,
                verdicts=tuple(
                    VerdictCount(status, n)
                    for status, n in sorted(Counter(v.status for v in r.verdicts.values()).items())
                ),
                readiness_direction=_direction(pairs),
                readiness_compared_count=len(pairs),
                weak_topics=tuple(
                    TopicCount(title, n)
                    for title, n in sorted(weak.items(), key=lambda kv: (-kv[1], kv[0]))[
                        :TOPICS_SHOWN
                    ]
                ),
                attendance=attendance.get(g.id),
                homework=homework.get(g.id),
                punctuality=punctuality.get(g.id),
            )
        )
    roster = sorted({sid for per in joined.values() for sid in per})
    return TutorFacts(
        clock.start,
        clock.end,
        tuple(classes),
        queue,
        await _marked(session, oid, roster, clock, group_ids),
    )


# ------------------------------------------------------------ student / parent


@dataclass(frozen=True)
class _ClassWeek:
    group: Group
    subject_name: str | None
    verdict: Verdict
    score: float | None
    grade: str | None
    direction: Direction | None
    chapters: _Chapters | None
    attendance: AttendanceFacts | None
    homework: HomeworkFacts | None


async def _student_weeks(session: AsyncSession, student: User, clock: _Clock) -> list[_ClassWeek]:
    """One student's week in each class they are enrolled in, inside their own
    organization (`SEC-7`, `SEC-8`): the enrolment is the scope, and a class of
    another organization is not read."""
    groups = list(
        (
            await session.scalars(
                select(Group)
                .options(selectinload(Group.subject))
                .join(GroupMember, GroupMember.group_id == Group.id)
                .where(
                    GroupMember.student_id == student.id,
                    Group.organization_id == student.organization_id,
                )
                .order_by(Group.name, Group.id)
            )
        ).all()
    )
    if not groups:
        return []
    oid, group_ids = student.organization_id, [g.id for g in groups]
    joined = await _joined(session, group_ids, only_student=student.id)
    attendance = await _attendance(session, oid, group_ids, joined, clock, student.id)
    homework, _punctuality = await _homework(session, oid, group_ids, joined, clock, student.id)
    readiness = await _readiness(session, groups, clock, only_student=student.id)
    slots, _exams = await _plan_slots(session, oid, group_ids)
    out = []
    for g in groups:
        r = readiness[g.id]
        verdict = r.verdicts.get(student.id)
        snap = r.now.get(student.id)
        if verdict is None:
            # Enrolment changed between reading the classes and the verdicts. One
            # learner's class must never stop the account's send.
            logger.warning(
                "student %s has no verdict in class %s; leaving it out of the week",
                student.id,
                g.id,
            )
            continue
        # The grade is shown only where the shared verdict gives a status: that
        # needs the org's boundaries, so with none set the grade is absent here
        # exactly as `class_verdicts` withholds it.
        has_grade = verdict.status != "not_enough_data" and snap is not None
        out.append(
            _ClassWeek(
                group=g,
                subject_name=g.subject.name if g.subject else None,
                verdict=verdict,
                score=snap.score if has_grade and snap else None,
                grade=snap.predicted_grade if has_grade and snap else None,
                direction=_direction(_pairs(r, [student.id])),
                chapters=_chapters(slots[g.id], clock) if g.id in slots else None,
                attendance=attendance.get(g.id),
                homework=homework.get(g.id),
            )
        )
    return out


async def build_student_facts(session: AsyncSession, student: User, window: Window) -> StudentFacts:
    if student.role != UserRole.student:
        raise ValueError("student facts are built for a student account")
    clock = await _clock(session, student.organization_id, window)
    weeks = await _student_weeks(session, student, clock)
    return StudentFacts(
        window_start=clock.start,
        window_end=clock.end,
        student_name=student.name,
        classes=tuple(
            StudentClassFacts(
                group_id=w.group.id,
                group_name=w.group.name,
                subject_name=w.subject_name,
                verdict=w.verdict.status,
                readiness_score=w.score,
                predicted_grade=w.grade,
                readiness_direction=w.direction,
                weak_topics=tuple(w.verdict.reason_topics),
                this_week_chapter=w.chapters.this_week if w.chapters else None,
                next_chapter=w.chapters.next if w.chapters else None,
                attendance=w.attendance,
                homework=w.homework,
            )
            for w in weeks
        ),
        marked=await _marked(session, student.organization_id, [student.id], clock),
    )


async def build_parent_facts(session: AsyncSession, parent: User, window: Window) -> ParentFacts:
    """One block per linked child. The link alone is not enough: the child must
    be in the parent's own organization, so a link row pointing across tenants
    reads as no child at all (`SEC-7`, `SEC-9`)."""
    if parent.role != UserRole.parent:
        raise ValueError("parent facts are built for a parent account")
    clock = await _clock(session, parent.organization_id, window)
    children = (
        await session.scalars(
            select(User)
            .join(ParentLink, ParentLink.student_id == User.id)
            .where(
                ParentLink.parent_id == parent.id,
                User.organization_id == parent.organization_id,
                User.role == UserRole.student,
            )
            .order_by(User.name, User.id)
        )
    ).all()
    linked = set(
        (
            await session.scalars(
                select(ParentLink.student_id).where(ParentLink.parent_id == parent.id)
            )
        ).all()
    )
    dropped = linked - {c.id for c in children}
    if dropped:
        logger.warning(
            "parent %s has %d link(s) that did not resolve to a child in organization %s: %s",
            parent.id,
            len(dropped),
            parent.organization_id,
            sorted(dropped),
        )
    blocks = []
    for child in children:
        weeks = await _student_weeks(session, child, clock)
        blocks.append(
            ParentChildFacts(
                child_name=child.name,
                child_id=child.id,
                classes=tuple(
                    ParentClassFacts(
                        group_name=w.group.name,
                        subject_name=w.subject_name,
                        verdict=w.verdict.status,
                        readiness_score=w.score,
                        predicted_grade=w.grade,
                        readiness_direction=w.direction,
                        chapter=w.chapters.this_week if w.chapters else None,
                        attendance=w.attendance,
                        homework=w.homework,
                    )
                    for w in weeks
                ),
            )
        )
    return ParentFacts(clock.start, clock.end, tuple(blocks), len(dropped))
