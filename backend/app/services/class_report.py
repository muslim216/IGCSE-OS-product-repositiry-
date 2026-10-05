"""The tutor's class report (task 8.6, AV-53, AV-112).

Everything revolves around the teaching plan (owner, 2026-10-05), so the report
leads with where the class is in its accepted plan, then reads the syllabus
against it (taught / not yet taught), then the class's mistake patterns, then
attendance. No AI is involved and nothing is stored: it is assembled at read time
from rows that already exist, so it can never disagree with the screens it
summarises. The weekly variant is the same call from a job
(`build_class_report(session, group, now=..., since=...)`); storage and the send
belong to that task, not this one.

Nothing here computes a number a sibling service already computes. Plan position
is `plan_progress`, the class headline is `build_class_overview`, topic means and
the weak-topic rule are `class_readiness`, attendance is `student_attendance`, and
the mistake gate mirrors `mistake_rollup` (`RISK-5`). This module only assembles.

The report is the tutor's document. The parent's is a different one and is not
built by filtering this one.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chapter,
    Group,
    GroupMember,
    Lesson,
    LessonAttendance,
    LessonTopic,
    Organization,
    PlanSlot,
    Topic,
    User,
)
from app.schemas.class_report import (
    AttendanceReport,
    ChapterReport,
    ClassReport,
    LearnerAttendance,
    PlanReport,
    ReportReadiness,
    TopicReport,
    UpNext,
)
from app.schemas.today import ClassWeakTopic
from app.services.attendance import counts_for_attendance, in_zone, student_attendance
from app.services.class_readiness import (
    ClassReadiness,
    TopicMean,
    class_readiness,
    latest_learner_snapshots,
    weak_topic_means,
)
from app.services.mistake_rollup import class_mistake_patterns
from app.services.plan_progress import NO_PROGRESS, Progress, SlotFact, class_progress, is_taught
from app.services.plan_start_times import resolve_zone
from app.services.readiness_config import resolve_readiness_config
from app.services.taught_before import taught_before_topic_ids
from app.services.teaching_plan import accepted_plan_for_group, next_unstarted_slot
from app.services.today import build_class_overview

#: The mistake window when the caller gives none: the last four weeks.
DEFAULT_WINDOW = timedelta(weeks=4)


class FutureSince(ValueError):
    """A mistake window that opens after the class's today has nothing to read."""


# ---------------------------------------------------------------- pure assembly


@dataclass(frozen=True)
class PlanCounts:
    planned: int
    taught: int
    left: int
    ahead_by: int


def count_plan(slots: list[SlotFact], today: date) -> PlanCounts:
    """Lesson totals over the plan's non-cancelled slots (`BE-4`). `ahead_by` is
    lessons already taught that were planned for a later day."""
    live = [s for s in slots if not s.cancelled]
    taught = [s for s in live if is_taught(s)]
    return PlanCounts(
        planned=len(live),
        taught=len(taught),
        left=len(live) - len(taught),
        # Strictly after today: a lesson planned for today and taught today is on time.
        ahead_by=sum(1 for s in taught if s.scheduled_date > today),
    )


def plan_position(progress: Progress, ahead_by: int, taught: int = 0) -> str | None:
    """Behind wins over ahead: a class with a gap is behind whatever else it has
    pulled forward. None before the plan has reached its first lesson, since
    "on track" about nothing is a claim without a basis (`PROD-2`)."""
    if progress.planned_to_date == 0 and progress.missed == 0 and taught == 0:
        return None
    if progress.missed > 0:
        return "behind"
    return "ahead" if ahead_by > 0 else "on_track"


def chapter_state(topics_total: int, topics_taught: int) -> str:
    if topics_taught == 0:
        return "not_started"
    return "taught" if topics_taught >= topics_total else "in_progress"


def attendance_rate(present: int, absent: int) -> float | None:
    marked = present + absent
    return present / marked if marked else None


def order_learners(rows: list[LearnerAttendance]) -> list[LearnerAttendance]:
    """Lowest rate first, unmarked after, then name."""
    return sorted(
        rows,
        key=lambda r: (r.rate is None, r.rate if r.rate is not None else 0.0, r.student_name),
    )


# ------------------------------------------------------------------ the reads


async def _plan_report(
    session: AsyncSession, group: Group, tutor: User, today: date, now: datetime
) -> tuple[PlanReport, dict[int, tuple[int, int]]]:
    """The plan section, and each chapter's (planned, taught) lesson counts."""
    plan = await accepted_plan_for_group(session, group.id)
    if plan is None:
        return PlanReport(has_plan=False), {}
    rows = (
        await session.execute(
            select(PlanSlot, Chapter)
            .join(Chapter, Chapter.id == PlanSlot.chapter_id)
            .where(PlanSlot.plan_id == plan.id)
        )
    ).all()
    facts = [
        SlotFact(
            slot.scheduled_date,
            slot.sequence,
            slot.id,
            chapter.id,
            chapter.code,
            chapter.title,
            slot.lesson_id is not None,
            slot.provenance,
            cancelled=slot.cancelled_at is not None,
        )
        for slot, chapter in rows
    ]
    counts = count_plan(facts, today)
    progress = (
        await class_progress(session, tutor, today, group.id, own_classes_only=False, now=now)
    ).get(group.id, ("", NO_PROGRESS))[1]
    per_chapter: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for f in facts:
        if f.cancelled:
            continue
        per_chapter[f.chapter_id][0] += 1
        per_chapter[f.chapter_id][1] += int(is_taught(f))

    nxt = await next_unstarted_slot(session, group.id)
    position = plan_position(progress, counts.ahead_by, counts.taught)
    started = position is not None
    return (
        PlanReport(
            has_plan=True,
            accepted_at=plan.accepted_at,
            exam_date=plan.exam_date,
            days_to_exam=(plan.exam_date - today).days,
            lessons_planned=counts.planned,
            lessons_taught=counts.taught,
            lessons_left=counts.left,
            lessons_due=progress.planned_to_date if started else None,
            behind_by=progress.missed if started else None,
            ahead_by=counts.ahead_by,
            position=position,  # type: ignore[arg-type]
            up_next=(
                UpNext(
                    scheduled_date=nxt.slot.scheduled_date,
                    chapter_code=nxt.chapter.code,
                    chapter_title=nxt.chapter.title,
                    topics=[t.title for t in nxt.topics],
                )
                if nxt
                else None
            ),
        ),
        {cid: (c[0], c[1]) for cid, c in per_chapter.items()},
    )


def _topic_report(
    t: Topic, taught_ids: set[int], means: dict[int, TopicMean], weak_ids: set[int]
) -> TopicReport:
    m = means.get(t.id)
    return TopicReport(
        topic_id=t.id,
        code=t.code,
        title=t.title,
        taught=t.id in taught_ids,
        avg_score=m.avg_score if m else None,
        student_count=m.student_count if m else None,
        weak=t.id in weak_ids,
        includes_tutor_estimate=m.includes_tutor_estimate if m else False,
    )


async def _chapter_reports(
    session: AsyncSession,
    group: Group,
    detail: ClassReadiness,
    weak: list[TopicMean],
    lesson_counts: dict[int, tuple[int, int]],
) -> list[ChapterReport]:
    # The subject's own chapters and topics (`SEC-8`): subjects are org-owned.
    chapters = list(
        await session.scalars(
            select(Chapter)
            .where(Chapter.subject_id == group.subject_id)
            .order_by(Chapter.position, Chapter.id)
        )
    )
    topics = list(
        await session.scalars(
            select(Topic).where(Topic.subject_id == group.subject_id).order_by(Topic.id)
        )
    )
    # Taught is derived from the lessons recorded for this class (`PROD-14`).
    taught_ids = set(
        await session.scalars(
            select(LessonTopic.topic_id)
            .join(Lesson, Lesson.id == LessonTopic.lesson_id)
            .where(Lesson.group_id == group.id, Lesson.organization_id == group.organization_id)
        )
    )
    # Plus what the tutor marked as taught before Avora (task 9.1b).
    taught_ids |= await taught_before_topic_ids(session, [group.id])
    means = {t.topic_id: t for t in detail.topic_means}
    weak_ids = {t.topic_id for t in weak}
    by_chapter: dict[int | None, list[Topic]] = defaultdict(list)
    for t in topics:
        by_chapter[t.chapter_id].append(t)

    out: list[ChapterReport] = []
    for ch in chapters:
        rows = [_topic_report(t, taught_ids, means, weak_ids) for t in by_chapter.get(ch.id, [])]
        taught_n = sum(1 for r in rows if r.taught)
        planned = lesson_counts.get(ch.id)
        out.append(
            ChapterReport(
                chapter_id=ch.id,
                code=ch.code,
                title=ch.title,
                topics_total=len(rows),
                topics_taught=taught_n,
                state=chapter_state(len(rows), taught_n),  # type: ignore[arg-type]
                lessons_planned=planned[0] if planned else None,
                lessons_taught=planned[1] if planned else None,
                topics=rows,
            )
        )
    loose = by_chapter.get(None, [])
    if loose:
        rows = [_topic_report(t, taught_ids, means, weak_ids) for t in loose]
        taught_n = sum(1 for r in rows if r.taught)
        out.append(
            ChapterReport(
                chapter_id=None,
                code="",
                title="Not in a chapter",
                topics_total=len(rows),
                topics_taught=taught_n,
                state=chapter_state(len(rows), taught_n),  # type: ignore[arg-type]
                topics=rows,
            )
        )
    return out


async def _lessons_not_taken(
    session: AsyncSession, group: Group, today: date, now_local: datetime
) -> int:
    """Distinct lessons nobody was marked at, by the one counting rule
    (`counts_for_attendance`): one unmarked lesson is one, not one per learner."""
    marked = select(LessonAttendance.lesson_id).where(
        LessonAttendance.organization_id == group.organization_id
    )
    lessons = await session.scalars(
        select(Lesson).where(
            Lesson.group_id == group.id,
            Lesson.organization_id == group.organization_id,
            Lesson.date <= today,
            Lesson.id.not_in(marked),
        )
    )
    return sum(1 for ls in lessons if counts_for_attendance(ls, None, None, today, now_local))


async def _attendance_report(
    session: AsyncSession, group: Group, now: datetime, today: date, now_local: datetime
) -> AttendanceReport:
    roster = (
        await session.execute(
            select(GroupMember.student_id, User.name)
            .join(User, User.id == GroupMember.student_id)
            .where(GroupMember.group_id == group.id)
        )
    ).all()
    learners: list[LearnerAttendance] = []
    for student_id, name in roster:
        # The one attendance read (services/attendance.py); one pass per learner,
        # bounded by the roster, and a report is on demand or weekly, not per view.
        att = await student_attendance(
            session,
            student_id=student_id,
            organization_id=group.organization_id,
            group_id=group.id,
            now=now,
        )
        learners.append(
            LearnerAttendance(
                student_id=student_id,
                student_name=name,
                present=att.present,
                absent=att.absent,
                not_taken=att.not_taken,
                rate=att.rate,
            )
        )
    present = sum(r.present for r in learners)
    absent = sum(r.absent for r in learners)
    return AttendanceReport(
        present=present,
        absent=absent,
        # Lessons, not learner-lessons: the per-learner column keeps its own count.
        not_taken=await _lessons_not_taken(session, group, today, now_local),
        rate=attendance_rate(present, absent),
        learners=order_learners(learners),
    )


async def build_class_report(
    session: AsyncSession, group: Group, *, now: datetime, since: date | None = None
) -> ClassReport:
    """One class's report as of `now` (aware). `since` opens the mistake window
    (default: four weeks back); plan position, topic coverage and attendance read
    the whole plan so far, because a window on "where are we in the plan" has no
    meaning. The caller has already proved the tutor may see this class
    (`SEC-7`, `API-7`); everything below is scoped by the class itself.

    A weekly job calls this directly with its own `now`.
    """
    # The overview reads `group.subject`; a lazy load in async would raise, and a
    # weekly job should not need to know that.
    await session.refresh(group, attribute_names=["subject"])
    tutor = await session.get(User, group.tutor_id)
    if tutor is None:  # RESTRICT on the FK makes this unreachable; never invent one.
        raise LookupError(f"class {group.id} has no tutor")
    org = await session.get(Organization, group.organization_id)
    zone = resolve_zone(tutor.time_zone, org.timezone if org else None, group.id)
    today = in_zone(now, zone).date()
    since = since or (today - DEFAULT_WINDOW)
    if since > today:
        raise FutureSince(since)

    overview = await build_class_overview(session, tutor, group)
    snapshots = await latest_learner_snapshots(session, [group.id])
    detail = await class_readiness(session, group.id, learners=snapshots[group.id])
    weak = await weak_topic_means(session, group, detail)
    config = await resolve_readiness_config(session, group.organization_id, group.subject_id)

    plan, lesson_counts = await _plan_report(session, group, tutor, today, now)
    return ClassReport(
        group_id=group.id,
        name=group.name,
        subject_name=overview.subject_name,
        generated_at=now,
        readiness=ReportReadiness(
            score=overview.score,
            predicted_grade=overview.predicted_grade,
            status=overview.status,
            boundaries_missing=overview.boundaries_missing,
            member_count=overview.member_count,
            students_with_evidence=overview.students_with_evidence,
        ),
        plan=plan,
        chapters=await _chapter_reports(session, group, detail, weak, lesson_counts),
        weak_topics=[
            ClassWeakTopic(
                topic_code=t.topic_code,
                topic_title=t.topic_title,
                avg_score=t.avg_score,
                student_count=t.student_count,
                includes_tutor_estimate=t.includes_tutor_estimate,
            )
            for t in weak
        ],
        weak_threshold=config.weak_threshold,
        mistakes=await class_mistake_patterns(
            session, group_id=group.id, subject_id=group.subject_id, since=since, zone=zone
        ),
        attendance=await _attendance_report(session, group, now, today, in_zone(now, zone)),
    )
