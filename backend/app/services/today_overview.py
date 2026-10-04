"""The tutor Overview's aggregates: the week at a glance, today's agenda, and a
card per class (coherence pass B, C.2, C.3).

Everything here is read for the tutor's own classes, scoped by the authenticated
user (`SEC-7`), in a fixed number of grouped queries however many classes there
are (`PERF-1`) — never a query per class, student or lesson.

Nothing defines a measurement a second time. Attendance counting is
`attendance.counts_for_attendance`; the topic share of a lesson is
`plan_timing.split_topics`; "behind" is `plan_progress.class_progress`; readiness
is `class_readiness.latest_learner_snapshots`, read at two moments. A figure with
nothing behind it is null or omitted, never 0 (`PROD-1`, `PROD-2`).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assignment,
    AssignmentStatus,
    AttendanceState,
    Chapter,
    FactorEvaluation,
    Group,
    GroupMember,
    Lesson,
    LessonAttendance,
    Organization,
    PlanSlot,
    QuestionMark,
    ReadinessFactor,
    RemarkRequest,
    RemarkRequestStatus,
    ScheduleSlot,
    Submission,
    SubmissionStatus,
    TeachingPlan,
    TeachingPlanStatus,
    Topic,
    User,
)
from app.schemas.today import (
    AgendaItem,
    ClassAttention,
    ClassCard,
    ClassTopicRef,
    LastLessonAttendance,
    RemarkItem,
    TodayOverview,
    WeekGlance,
)
from app.services.attendance import counts_for_attendance, in_zone
from app.services.class_readiness import LearnerSnapshot, latest_learner_snapshots
from app.services.plan_progress import Progress, class_progress
from app.services.plan_start_times import timetable_start_times
from app.services.plan_timing import slot_end_utc, slot_start_utc, split_topics
from app.services.readiness_shared import CONFIDENT, trend_direction
from app.services.teaching_plan import STARTED_PROVENANCE, effective_start_time
from app.services.timezones import effective_timezone
from app.services.today import pending_review_count, tutor_groups

#: A student counts as "dropped" when their latest readiness score is at least
#: this many points below their latest score from a week or more ago. Chosen as
#: above `DIRECTION_NOISE_BAND` (3.0): a drop worth naming is more than the
#: movement the app already treats as noise.
READINESS_DROP_THRESHOLD = 5.0
#: How old the comparison snapshot must be, in days ("since last week").
READINESS_COMPARISON_DAYS = 7
#: A topic score under this is "below 50%" — the figure the card quotes.
WEAK_TOPIC_BELOW = 50.0
#: Names listed in a card's reason before "and N more".
NAMES_SHOWN = 3


@dataclass(frozen=True)
class SlotRow:
    slot_id: int
    plan_id: int
    group_id: int
    chapter_id: int
    chapter_code: str
    chapter_title: str
    scheduled_date: date
    start_time: time | None
    lesson_id: int | None
    started: bool
    cancelled: bool
    lesson_minutes: int


def _slot_select():
    return (
        select(
            PlanSlot.id,
            PlanSlot.plan_id,
            TeachingPlan.group_id,
            Chapter.id,
            Chapter.code,
            Chapter.title,
            PlanSlot.scheduled_date,
            PlanSlot.start_time,
            PlanSlot.lesson_id,
            PlanSlot.provenance,
            PlanSlot.cancelled_at,
            TeachingPlan.lesson_minutes,
        )
        .select_from(PlanSlot)
        .join(TeachingPlan, TeachingPlan.id == PlanSlot.plan_id)
        .join(Chapter, Chapter.id == PlanSlot.chapter_id)
    )


def _slot_rows(rows) -> list[SlotRow]:
    return [
        SlotRow(
            slot_id=r[0],
            plan_id=r[1],
            group_id=r[2],
            chapter_id=r[3],
            chapter_code=r[4],
            chapter_title=r[5],
            scheduled_date=r[6],
            start_time=r[7],
            lesson_id=r[8],
            started=r[9] in STARTED_PROVENANCE,
            cancelled=r[10] is not None,
            lesson_minutes=r[11],
        )
        for r in rows
    ]


def _names(names: list[str]) -> str:
    shown = names[:NAMES_SHOWN]
    rest = len(names) - len(shown)
    return ", ".join(shown) + (f" and {rest} more" if rest else "")


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


async def _topic_shares(db: AsyncSession, slots: list[SlotRow]) -> dict[int, list[ClassTopicRef]]:
    """{slot_id: that lesson's topics}, for many slots in two queries. The same
    split as `teaching_plan.topic_share` (one definition: `split_topics`), done
    over every chapter at once."""
    if not slots:
        return {}
    plan_ids = {s.plan_id for s in slots}
    chapter_ids = {s.chapter_id for s in slots}
    ordered: dict[tuple[int, int], list[int]] = defaultdict(list)
    for plan_id, chapter_id, slot_id in (
        await db.execute(
            select(PlanSlot.plan_id, PlanSlot.chapter_id, PlanSlot.id)
            .where(
                PlanSlot.plan_id.in_(plan_ids),
                PlanSlot.chapter_id.in_(chapter_ids),
                PlanSlot.cancelled_at.is_(None),
            )
            .order_by(PlanSlot.scheduled_date, PlanSlot.sequence, PlanSlot.id)
        )
    ).all():
        ordered[(plan_id, chapter_id)].append(slot_id)
    topics: dict[int, list[ClassTopicRef]] = defaultdict(list)
    for topic in (
        await db.scalars(select(Topic).where(Topic.chapter_id.in_(chapter_ids)).order_by(Topic.id))
    ).all():
        assert topic.chapter_id is not None
        topics[topic.chapter_id].append(
            ClassTopicRef(id=topic.id, code=topic.code, title=topic.title)
        )
    out: dict[int, list[ClassTopicRef]] = {}
    for s in slots:
        order = ordered.get((s.plan_id, s.chapter_id), [])
        if s.slot_id not in order or s.cancelled:
            out[s.slot_id] = []
            continue
        out[s.slot_id] = split_topics(
            topics.get(s.chapter_id, []), order.index(s.slot_id), len(order)
        )
    return out


async def build_overview(
    db: AsyncSession, user: User, now: datetime | None = None
) -> TodayOverview:
    """`now` exists so tests can pin the clock; production passes nothing."""
    now_utc = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    org = await db.get(Organization, user.organization_id)
    zone = effective_timezone(user.time_zone, org.timezone if org else None)
    now_local = in_zone(now_utc, zone)
    today = now_local.date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    groups = [
        g for g in await tutor_groups(db, user.id) if g.organization_id == user.organization_id
    ]
    group_ids = [g.id for g in groups]
    marking_waiting = await pending_review_count(db, user.organization_id)
    if not group_ids:
        return TodayOverview(
            week=WeekGlance(
                week_start=week_start,
                week_end=week_end,
                lessons_planned=0,
                lessons_taught=0,
                marking_waiting=marking_waiting,
                attendance_present=0,
                attendance_absent=0,
                attendance_not_taken=0,
                attendance_rate=None,
                readiness_drop_count=0,
                readiness_compared_count=0,
                readiness_drop_threshold=READINESS_DROP_THRESHOLD,
            ),
            agenda=[],
            classes=[],
            remarks=await _remarks(db, user, {}),
        )
    group_by_id = {g.id: g for g in groups}

    # ---- plan slots and lessons of the week --------------------------------
    accepted = TeachingPlan.status == TeachingPlanStatus.accepted
    week_slots = _slot_rows(
        (
            await db.execute(
                _slot_select().where(
                    TeachingPlan.organization_id == user.organization_id,
                    TeachingPlan.group_id.in_(group_ids),
                    accepted,
                    PlanSlot.scheduled_date.between(week_start, week_end),
                )
            )
        ).all()
    )
    live_slots = [s for s in week_slots if not s.cancelled]
    week_lessons = list(
        (
            await db.scalars(
                select(Lesson).where(
                    Lesson.organization_id == user.organization_id,
                    Lesson.group_id.in_(group_ids),
                    Lesson.date.between(week_start, week_end),
                )
            )
        ).all()
    )
    slot_lesson_ids = {s.lesson_id for s in live_slots if s.lesson_id is not None}
    # A lesson no slot of this week accounts for is its own planned-and-taught lesson.
    adhoc = [lesson for lesson in week_lessons if lesson.id not in slot_lesson_ids]
    lessons_planned = len(live_slots) + len(adhoc)
    lessons_taught = sum(1 for s in live_slots if s.lesson_id is not None or s.started) + len(adhoc)

    # ---- attendance --------------------------------------------------------
    prior_latest = (
        select(Lesson.group_id.label("g"), func.max(Lesson.date).label("d"))
        .where(Lesson.group_id.in_(group_ids), Lesson.date < today)
        .group_by(Lesson.group_id)
        .subquery()
    )
    earlier = list(
        (
            await db.scalars(
                select(Lesson).join(
                    prior_latest,
                    (Lesson.group_id == prior_latest.c.g) & (Lesson.date == prior_latest.c.d),
                )
            )
        ).all()
    )
    pool: dict[int, Lesson] = {
        lesson.id: lesson for lesson in [*week_lessons, *earlier] if lesson.date <= today
    }
    members: dict[int, dict[int, date]] = defaultdict(dict)
    for gid, sid, joined in (
        await db.execute(
            select(GroupMember.group_id, GroupMember.student_id, GroupMember.created_at).where(
                GroupMember.group_id.in_(group_ids)
            )
        )
    ).all():
        members[gid][sid] = in_zone(joined, zone).date()
    marks: dict[int, dict[int, AttendanceState]] = defaultdict(dict)
    if pool:
        for lid, sid, state in (
            await db.execute(
                select(
                    LessonAttendance.lesson_id, LessonAttendance.student_id, LessonAttendance.state
                ).where(
                    LessonAttendance.lesson_id.in_(list(pool)),
                    LessonAttendance.organization_id == user.organization_id,
                )
            )
        ).all():
            marks[lid][sid] = state

    def tally(lesson: Lesson) -> tuple[int, int, int]:
        """(present, absent, not taken) for one lesson, by the shared definition:
        everyone enrolled plus anyone with a mark who has since left."""
        present = absent = not_taken = 0
        for sid in set(members[lesson.group_id]) | set(marks[lesson.id]):
            state = marks[lesson.id].get(sid)
            if not counts_for_attendance(
                lesson,
                state,
                members[lesson.group_id].get(sid),
                today,
                now_local,
            ):
                continue
            if state is None:
                not_taken += 1
            elif state == AttendanceState.present:
                present += 1
            else:
                absent += 1
        return present, absent, not_taken

    tallies = {lid: tally(lesson) for lid, lesson in pool.items()}
    week_present = sum(tallies[lesson.id][0] for lesson in week_lessons if lesson.id in tallies)
    week_absent = sum(tallies[lesson.id][1] for lesson in week_lessons if lesson.id in tallies)
    week_not_taken = sum(tallies[lesson.id][2] for lesson in week_lessons if lesson.id in tallies)
    marked = week_present + week_absent
    last_lesson: dict[int, LastLessonAttendance] = {}
    for gid in group_ids:
        # A lesson today that has not ended and has no marks is not yet a lesson
        # with attendance to report: the previous one is "the last lesson".
        eligible = [
            lesson
            for lesson in pool.values()
            if lesson.group_id == gid and (lesson.date < today or any(tallies[lesson.id]))
        ]
        if not eligible:
            continue
        latest = max(
            eligible, key=lambda lesson: (lesson.date, lesson.start_time or time.min, lesson.id)
        )
        p, a, n = tallies[latest.id]
        if p + a + n == 0:
            # Nobody to count (no enrolled students, no marks): nothing to report,
            # and never a "0 present".
            continue
        last_lesson[gid] = LastLessonAttendance(
            lesson_id=latest.id, lesson_date=latest.date, present=p, absent=a, not_taken=n
        )

    # ---- readiness: now against a week ago ---------------------------------
    now_snaps = await latest_learner_snapshots(db, group_ids)
    then_snaps = await latest_learner_snapshots(
        db, group_ids, before=now_utc - timedelta(days=READINESS_COMPARISON_DAYS)
    )
    dropped: dict[int, list[LearnerSnapshot]] = defaultdict(list)
    class_pairs: dict[int, list[tuple[float, float]]] = defaultdict(list)
    compared_students: set[int] = set()
    dropped_students: set[int] = set()
    for gid in group_ids:
        for sid, latest_snap in now_snaps.get(gid, {}).items():
            old = then_snaps.get(gid, {}).get(sid)
            if latest_snap.score is None or old is None or old.score is None:
                continue
            if old.evaluation_run_id == latest_snap.evaluation_run_id:
                # The same run at both ends is not a week of history.
                continue
            compared_students.add(sid)
            class_pairs[gid].append((old.score, latest_snap.score))
            if old.score - latest_snap.score >= READINESS_DROP_THRESHOLD:
                dropped_students.add(sid)
                dropped[gid].append(latest_snap)

    # ---- per-class facts ---------------------------------------------------
    plan_groups = set(
        (
            await db.scalars(
                select(TeachingPlan.group_id).where(
                    TeachingPlan.organization_id == user.organization_id,
                    TeachingPlan.group_id.in_(group_ids),
                    accepted,
                )
            )
        ).all()
    )
    unstarted = (
        _slot_select()
        .add_columns(
            func.row_number()
            .over(
                partition_by=TeachingPlan.group_id,
                order_by=(PlanSlot.scheduled_date, PlanSlot.sequence, PlanSlot.id),
            )
            .label("rn")
        )
        .where(
            TeachingPlan.organization_id == user.organization_id,
            TeachingPlan.group_id.in_(group_ids),
            accepted,
            PlanSlot.lesson_id.is_(None),
            PlanSlot.provenance.not_in(STARTED_PROVENANCE),
            PlanSlot.cancelled_at.is_(None),
        )
        .subquery()
    )
    next_slot: dict[int, tuple[str, str]] = {
        row.group_id: (row.code, row.title)
        for row in (await db.execute(select(unstarted).where(unstarted.c.rn == 1))).all()
    }
    progress: dict[int, Progress] = {
        gid: p for gid, (_name, p) in (await class_progress(db, user, today, now=now_utc)).items()
    }

    hw_members = {gid: len(m) for gid, m in members.items()}
    submitted = (
        select(
            Assignment.group_id.label("g"),
            Assignment.id.label("a"),
            func.count(func.distinct(GroupMember.student_id)).label("n"),
        )
        .select_from(Assignment)
        .outerjoin(Submission, Submission.work_id == Assignment.work_id)
        .outerjoin(
            GroupMember,
            (GroupMember.group_id == Assignment.group_id)
            & (GroupMember.student_id == Submission.student_id),
        )
        .where(Assignment.group_id.in_(group_ids), Assignment.status == AssignmentStatus.published)
        .group_by(Assignment.group_id, Assignment.id)
    )
    hw_out: dict[int, int] = defaultdict(int)
    hw_missing: dict[int, int] = defaultdict(int)
    for gid, _aid, n in (await db.execute(submitted)).all():
        missing = hw_members.get(gid, 0) - n
        if missing > 0:
            hw_out[gid] += 1
            hw_missing[gid] += missing

    marking_by_group: dict[int, int] = {}
    for gid, n in (
        await db.execute(
            select(Assignment.group_id, func.count(Submission.id))
            .join(Assignment, Assignment.work_id == Submission.work_id)
            .where(
                Assignment.group_id.in_(group_ids),
                Submission.status == SubmissionStatus.needs_review,
            )
            .group_by(Assignment.group_id)
        )
    ).all():
        marking_by_group[gid] = n

    # Students under the bar, per class and topic, from each learner's own
    # latest run (never an older run's score) and only confident evidence.
    run_owners: dict[str, list[tuple[int, LearnerSnapshot]]] = defaultdict(list)
    for gid, learners in now_snaps.items():
        for snap in learners.values():
            run_owners[snap.evaluation_run_id].append((gid, snap))
    weak: dict[int, dict[int, tuple[str, str, list[LearnerSnapshot]]]] = defaultdict(dict)
    if run_owners:
        for run_id, topic_id, code, title in (
            await db.execute(
                select(
                    FactorEvaluation.evaluation_run_id,
                    FactorEvaluation.topic_id,
                    Topic.code,
                    Topic.title,
                )
                .join(Topic, Topic.id == FactorEvaluation.topic_id)
                .where(
                    FactorEvaluation.evaluation_run_id.in_(list(run_owners)),
                    FactorEvaluation.factor == ReadinessFactor.topic_mastery,
                    FactorEvaluation.score.is_not(None),
                    FactorEvaluation.score < WEAK_TOPIC_BELOW,
                    FactorEvaluation.confidence.in_(CONFIDENT),
                )
            )
        ).all():
            for gid, snap in run_owners[run_id]:
                entry = weak[gid].setdefault(topic_id, (code, title, []))
                entry[2].append(snap)

    # ---- the cards ---------------------------------------------------------
    cards: list[ClassCard] = []
    for gid in group_ids:
        prog = progress.get(gid)
        missed = prog.missed if prog else 0
        if gid not in plan_groups:
            plan_state = "none"
        elif missed > 0:
            plan_state = "behind"
        elif gid in next_slot:
            plan_state = "on_track"
        else:
            plan_state = "complete"
        chapter = next_slot.get(gid)
        pairs = class_pairs.get(gid, [])
        direction = (
            trend_direction(
                [
                    sum(o for o, _ in pairs) / len(pairs),
                    sum(n for _, n in pairs) / len(pairs),
                ]
            )
            if pairs
            else None
        )
        cards.append(
            ClassCard(
                group_id=gid,
                plan_state=plan_state,
                plan_chapter_code=chapter[0] if chapter else None,
                plan_chapter_title=chapter[1] if chapter else None,
                plan_missed=missed,
                plan_earliest_missed_date=prog.earliest_missed_date if prog and missed else None,
                readiness_direction=direction,
                readiness_compared_count=len(pairs),
                last_lesson=last_lesson.get(gid),
                homework_out=hw_out.get(gid, 0),
                homework_missing=hw_missing.get(gid, 0),
                attention=_attention(
                    weak.get(gid, {}),
                    dropped.get(gid, []),
                    prog if missed else None,
                    marking_by_group.get(gid, 0),
                ),
            )
        )

    agenda = await _agenda(
        db, user, groups, group_by_id, week_slots, week_lessons, plan_groups, today, zone
    )
    return TodayOverview(
        week=WeekGlance(
            week_start=week_start,
            week_end=week_end,
            lessons_planned=lessons_planned,
            lessons_taught=lessons_taught,
            marking_waiting=marking_waiting,
            attendance_present=week_present,
            attendance_absent=week_absent,
            attendance_not_taken=week_not_taken,
            attendance_rate=week_present / marked if marked else None,
            readiness_drop_count=len(dropped_students),
            readiness_compared_count=len(compared_students),
            readiness_drop_threshold=READINESS_DROP_THRESHOLD,
        ),
        agenda=agenda,
        classes=cards,
        remarks=await _remarks(db, user, {g.id: g.name for g in groups}),
    )


def _attention(
    weak_topics: dict[int, tuple[str, str, list[LearnerSnapshot]]],
    dropped: list[LearnerSnapshot],
    behind: Progress | None,
    marking: int,
) -> ClassAttention | None:
    """The class's single most important item, most specific first: students
    below the bar on a named topic, then students whose readiness fell, then
    lessons not recorded against the plan, then marking waiting. Always with its
    reason — a bare "needs a look" is not an answer (C.2)."""
    if weak_topics:
        # The topic the most students are under the bar on; lowest code breaks ties.
        topic_id, (code, title, snaps) = min(
            weak_topics.items(), key=lambda kv: (-len(kv[1][2]), kv[1][0])
        )
        snaps = sorted(snaps, key=lambda s: (s.student_name.lower(), s.student_id))
        return ClassAttention(
            kind="weak_topic",
            message=f"{_names([s.student_name for s in snaps])} below {WEAK_TOPIC_BELOW:.0f}% on {code} {title}",
            topic_id=topic_id,
            student_ids=[s.student_id for s in snaps],
            student_names=[s.student_name for s in snaps],
        )
    if dropped:
        snaps = sorted(dropped, key=lambda s: (s.student_name.lower(), s.student_id))
        return ClassAttention(
            kind="readiness_drop",
            message=(
                f"{_names([s.student_name for s in snaps])} dropped "
                f"{READINESS_DROP_THRESHOLD:.0f}+ points in readiness since last week"
            ),
            student_ids=[s.student_id for s in snaps],
            student_names=[s.student_name for s in snaps],
        )
    if behind is not None:
        n = behind.missed
        first = (
            f", starting with Chapter {behind.earliest_missed_chapter[1]} "
            f"{behind.earliest_missed_chapter[2]}"
            if behind.earliest_missed_chapter
            else ""
        )
        return ClassAttention(
            kind="behind_plan",
            message=f"{n} planned {'lesson' if n == 1 else 'lessons'} not recorded{first}",
        )
    if marking > 0:
        return ClassAttention(
            kind="marking",
            message=f"{marking} {'submission' if marking == 1 else 'submissions'} waiting for your marking",
        )
    return None


async def _agenda(
    db: AsyncSession,
    user: User,
    groups: list[Group],
    group_by_id: dict[int, Group],
    week_slots: list[SlotRow],
    week_lessons: list[Lesson],
    plan_groups: set[int],
    today: date,
    zone: str | None,
) -> list[AgendaItem]:
    """Today's lessons: each plan slot dated today that nobody has taught, each
    lesson recorded today, and — for a class with no accepted plan — its
    timetable slot for today. A cancelled slot is not a lesson."""
    group_ids = [g.id for g in groups]
    todays_lessons = [lesson for lesson in week_lessons if lesson.date == today]
    open_slots = [
        s
        for s in week_slots
        if s.scheduled_date == today and not s.cancelled and s.lesson_id is None and not s.started
    ]
    linked: dict[int, SlotRow] = {}
    if todays_lessons:
        for row in _slot_rows(
            (
                await db.execute(
                    _slot_select().where(
                        TeachingPlan.organization_id == user.organization_id,
                        PlanSlot.lesson_id.in_([lesson.id for lesson in todays_lessons]),
                    )
                )
            ).all()
        ):
            assert row.lesson_id is not None
            linked[row.lesson_id] = row
    timetables = await timetable_start_times(db, group_ids)
    shares = await _topic_shares(db, [*open_slots, *linked.values()])

    items: list[AgendaItem] = []

    def when(day: date, start: time | None, minutes: int):
        if start is None:
            return None, None
        return slot_start_utc(day, start, zone), slot_end_utc(day, start, minutes, zone)

    for lesson in todays_lessons:
        group = group_by_id[lesson.group_id]
        slot = linked.get(lesson.id)
        starts, ends = when(today, lesson.start_time, lesson.duration_min)
        items.append(
            AgendaItem(
                key=f"lesson-{lesson.id}",
                group_id=group.id,
                group_name=group.name,
                subject_name=group.subject.name if group.subject else "",
                slot_id=slot.slot_id if slot else None,
                lesson_id=lesson.id,
                source="lesson",
                start_time=lesson.start_time,
                starts_at=starts,
                ends_at=ends,
                duration_min=lesson.duration_min,
                chapter_id=slot.chapter_id if slot else None,
                chapter_code=slot.chapter_code if slot else None,
                chapter_title=slot.chapter_title if slot else None,
                topics=shares.get(slot.slot_id, []) if slot else [],
                local_date=today,
                recorded=True,
            )
        )
    for s in open_slots:
        group = group_by_id[s.group_id]
        start = effective_start_time(s.start_time, timetables.get(group.id, {}), s.scheduled_date)
        starts, ends = when(today, start, s.lesson_minutes)
        items.append(
            AgendaItem(
                key=f"slot-{s.slot_id}",
                group_id=group.id,
                group_name=group.name,
                subject_name=group.subject.name if group.subject else "",
                slot_id=s.slot_id,
                source="plan",
                start_time=start,
                starts_at=starts,
                ends_at=ends,
                duration_min=s.lesson_minutes,
                chapter_id=s.chapter_id,
                chapter_code=s.chapter_code,
                chapter_title=s.chapter_title,
                topics=shares.get(s.slot_id, []),
                local_date=today,
            )
        )
    covered = {i.group_id for i in items}
    for slot_row in (
        await db.scalars(
            select(ScheduleSlot).where(
                ScheduleSlot.group_id.in_(group_ids), ScheduleSlot.weekday == today.weekday()
            )
        )
    ).all():
        # A class with an accepted plan is governed by the plan: its cancelled or
        # already-taught slot must not come back as a timetable row.
        if slot_row.group_id in plan_groups or slot_row.group_id in covered:
            continue
        group = group_by_id[slot_row.group_id]
        starts, ends = when(today, slot_row.start_time, slot_row.duration_min)
        items.append(
            AgendaItem(
                key=f"timetable-{slot_row.id}",
                group_id=group.id,
                group_name=group.name,
                subject_name=group.subject.name if group.subject else "",
                source="timetable",
                start_time=slot_row.start_time,
                starts_at=starts,
                ends_at=ends,
                duration_min=slot_row.duration_min,
                local_date=today,
            )
        )
    items.sort(key=lambda i: (i.start_time is None, i.start_time or time.min, i.key))
    return items


async def _remarks(db: AsyncSession, user: User, names: dict[int, str]) -> list[RemarkItem]:
    """Open remark requests on submissions still waiting for the tutor, in the
    tutor's own classes. A remark puts the submission back in the queue
    (`api/submissions.request_remark`), so the queue row alone could only say
    "some marks need your decision"; this says a student asked."""
    if not names:
        return []
    rows = (
        await db.execute(
            select(
                Submission.id,
                Assignment.title,
                User.name,
                Assignment.group_id,
                RemarkRequest.reason,
            )
            .join(QuestionMark, QuestionMark.submission_id == Submission.id)
            .join(RemarkRequest, RemarkRequest.question_mark_id == QuestionMark.id)
            .join(Assignment, Assignment.work_id == Submission.work_id)
            .join(User, User.id == Submission.student_id)
            .where(
                Assignment.group_id.in_(list(names)),
                RemarkRequest.status == RemarkRequestStatus.open,
                Submission.status == SubmissionStatus.needs_review,
            )
            .order_by(RemarkRequest.created_at, RemarkRequest.id)
        )
    ).all()
    # One row per submission, not per remarked question: the tutor opens the
    # submission either way, and a list key must be unique. The earliest
    # request's reason is the one quoted.
    items: dict[int, RemarkItem] = {}
    for sid, title, student, gid, reason in rows:
        items.setdefault(
            sid,
            RemarkItem(
                submission_id=sid,
                assignment_title=title,
                student_name=student,
                group_name=names[gid],
                reason=reason,
            ),
        )
    return list(items.values())
