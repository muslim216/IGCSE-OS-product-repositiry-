"""The tutor home and class-page aggregates.

The orchestration lives here rather than in the router (BE-1, BE-2): api/today.py
is request/response wiring only. Everything below is built from a **bounded**
number of queries — the surface it replaces issued one analytics request per
class, each of which looped `db.get(User)` plus a readiness select per learner
(PERF-1).
"""

from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Assignment,
    GradeBoundary,
    Group,
    GroupMember,
    Organization,
    PastPaper,
    ReadinessHistory,
    ScheduleSlot,
    Subject,
    Submission,
    Topic,
    TopicReadiness,
    User,
)
from app.schemas.groups import UpcomingScheduleSlot
from app.schemas.today import (
    ClassLearnerRow,
    ClassOverview,
    ClassStripRow,
    ClassWeakTopic,
    TodayView,
)
from app.services.grades import grade_band, predict_grade
from app.services.groups import class_health, review_queue_predicate
from app.services.groups import summaries as group_summaries
from app.services.readiness_summary import CONFIDENT, trend_direction
from app.services.timezones import today_weekday

#: Exceptions first. A tutor opening their home is looking for what needs them,
#: so the strip is ordered by how much attention a class wants, and the healthy
#: tail collapses to one line on the surface.
_STATUS_ORDER = {"at_risk": 0, "needs_attention": 1, None: 2, "on_track": 3}


async def tutor_groups(db: AsyncSession, tutor_id: int) -> Sequence[Group]:
    return (
        await db.scalars(
            select(Group)
            .where(Group.tutor_id == tutor_id)
            .options(selectinload(Group.subject))
            .order_by(Group.created_at)
        )
    ).all()


async def org_boundaries(db: AsyncSession, organization_id: int) -> dict[int, list[dict]]:
    """Every organization grade-boundary override, keyed by subject, in one query.

    Calling resolve_grade_boundaries() per class would reintroduce exactly the
    per-class round trip these aggregates exist to remove. The precedence it
    implements is preserved by `boundaries_for()`: the organization's override if
    it has one, the global Subject default otherwise (RISK-5).
    """
    overrides: dict[int, list[dict]] = defaultdict(list)
    for row in (
        await db.scalars(
            select(GradeBoundary).where(GradeBoundary.organization_id == organization_id)
        )
    ).all():
        overrides[row.subject_id].append({"grade": row.grade_label, "min": row.min_percentage})
    return {
        subject_id: sorted(bands, key=lambda b: b["min"], reverse=True)
        for subject_id, bands in overrides.items()
    }


def boundaries_for(overrides: dict[int, list[dict]], subject: Subject | None) -> list[dict]:
    if subject is None:
        return []
    return overrides.get(subject.id) or subject.grade_boundaries or []


async def pending_review_count(db: AsyncSession, organization_id: int) -> int:
    """How many submissions the review queue would list for this tutor.

    Submission is polymorphic: a homework submission has `assignment_id` set and
    a past-paper submission has `past_paper_id` set instead (API-20). Counting
    only through an inner join to Assignment — which is what
    services/groups.summaries() does, correctly, for its *per-class* number —
    silently drops every past paper, so the home could report a clear day while
    past-paper work sat in the review queue.

    The predicate itself is review_queue's, shared rather than restated: this
    count is the headline the tutor clicks to reach that page, so any difference
    between them is visible as a wrong number (see review_queue_predicate).
    """
    return (
        await db.scalar(
            select(func.count(Submission.id))
            .outerjoin(Assignment, Assignment.id == Submission.assignment_id)
            .outerjoin(Group, Group.id == Assignment.group_id)
            .outerjoin(PastPaper, PastPaper.id == Submission.past_paper_id)
            .where(*review_queue_predicate(organization_id))
        )
    ) or 0


async def today_lessons(
    db: AsyncSession, tutor_id: int, organization_id: int
) -> list[UpcomingScheduleSlot]:
    """The tutor's lessons for *their* today.

    This lives in the service layer because two routes need it — /me/today-lessons
    and the home aggregate — and a router must never call another router (BE-2).
    It previously did: api/today.py imported api/me.py's handler, so adding a
    dependency or a Query parameter to that route would have silently changed the
    aggregate, and the timezone rule below was a side effect of a route.
    """
    # "Today" is the tutor's today, not the server's. A tutor in Cairo opening
    # this at 01:00 local is on tomorrow's weekday while UTC is still on
    # yesterday's, and this answer is entirely *which day it is*.
    org = await db.get(Organization, organization_id)
    weekday = today_weekday(org.timezone if org else None)
    rows = (
        await db.execute(
            select(ScheduleSlot, Group, func.count(GroupMember.id))
            .join(Group, Group.id == ScheduleSlot.group_id)
            .outerjoin(GroupMember, GroupMember.group_id == Group.id)
            .where(Group.tutor_id == tutor_id, ScheduleSlot.weekday == weekday)
            .options(selectinload(Group.subject))
            .group_by(ScheduleSlot.id, Group.id)
            .order_by(ScheduleSlot.start_time)
        )
    ).all()
    return [
        UpcomingScheduleSlot(
            id=slot.id,
            group_id=group.id,
            group_name=f"{group.name} ({count} student{'s' if count != 1 else ''})",
            # Guarded like every other read of this relationship in the module
            # (boundaries_for, the class strip): one unguarded access here would
            # fail /me/today-lessons and the whole home aggregate together.
            subject_name=group.subject.name if group.subject else "",
            weekday=slot.weekday,
            start_time=slot.start_time,
            duration_min=slot.duration_min,
            title=slot.title,
        )
        for slot, group, count in rows
    ]


async def build_today(db: AsyncSession, user: User) -> TodayView:
    """The tutor's home. Scoped by the authenticated user's own classes — never
    by a path or body parameter (SEC-7)."""
    lessons = await today_lessons(db, user.id, user.organization_id)
    groups = await tutor_groups(db, user.id)
    summaries = await group_summaries(db, [g.id for g in groups])
    health = await class_health(db, groups)
    overrides = await org_boundaries(db, user.organization_id)

    rows: list[ClassStripRow] = []
    for group in groups:
        summary = summaries[group.id]
        score, _contributing = health.get(group.id, (None, 0))
        boundaries = boundaries_for(overrides, group.subject)
        # No score means no grade and no colour — never a defaulted one (PROD-2).
        grade = predict_grade(score, boundaries) if score is not None and boundaries else None
        rows.append(
            ClassStripRow(
                group_id=group.id,
                name=group.name,
                subject_name=group.subject.name if group.subject else "",
                score=score,
                predicted_grade=grade,
                status=grade_band(grade, boundaries),
                boundaries_missing=not boundaries,
                member_count=summary.member_count,
                students_with_evidence=summary.students_with_evidence,
                awaiting_review_count=summary.awaiting_review_count,
            )
        )
    rows.sort(key=lambda r: (_STATUS_ORDER.get(r.status, 2), -r.awaiting_review_count, r.name))

    return TodayView(
        classes=rows,
        lessons=lessons,
        review_count=await pending_review_count(db, user.organization_id),
        class_count=len(rows),
        joined_student_count=sum(r.member_count for r in rows),
        classes_with_evidence=sum(1 for r in rows if r.score is not None),
    )


async def build_class_overview(db: AsyncSession, user: User, group: Group) -> ClassOverview:
    """The class page's headline.

    NEEDS YOU is selected on **direction, not level**: a learner sliding from a
    grade 8 to a 6 is the one the tutor can still help, while a learner who has
    been a stable grade 4 all year is why the class carries its status and is not
    news. Both still appear under Learners — nothing is hidden, it is ordered.

    Score and direction both come from the **v1** engine (TopicReadiness and
    ReadinessHistory respectively). That pairing is deliberate and is what
    readiness_summary.py requires: each engine reads its own history, so the
    arrow always describes the score it sits beside (PROD-1). Mixing a v1 score
    with a v2-derived arrow is the bug that rule exists to prevent. That this
    surface answers from v1 while the student's own readiness answers from v2 is
    RISK-5, pre-existing and out of scope here.
    """
    overrides = await org_boundaries(db, user.organization_id)
    boundaries = boundaries_for(overrides, group.subject)
    summaries = await group_summaries(db, [group.id])
    summary = summaries[group.id]
    class_score, _ = (await class_health(db, [group])).get(group.id, (None, 0))

    members = (
        await db.execute(
            select(User.id, User.name)
            .join(GroupMember, GroupMember.student_id == User.id)
            .where(GroupMember.group_id == group.id)
        )
    ).all()
    member_ids = [mid for mid, _ in members]
    names = dict(members)

    # Per-learner weighted readiness, for every learner at once.
    per_student: dict[int, tuple[float, float]] = {}
    topic_scores: dict[int, list[float]] = defaultdict(list)
    topic_meta: dict[int, tuple[str, str]] = {}
    if member_ids:
        for student_id, topic_id, code, title, weight, score in (
            await db.execute(
                select(
                    TopicReadiness.student_id,
                    Topic.id,
                    Topic.code,
                    Topic.title,
                    Topic.weight,
                    TopicReadiness.score,
                )
                .join(Topic, Topic.id == TopicReadiness.topic_id)
                .where(
                    TopicReadiness.student_id.in_(member_ids),
                    Topic.subject_id == group.subject_id,
                    TopicReadiness.confidence.in_(CONFIDENT),
                )
            )
        ).all():
            weighted, total = per_student.get(student_id, (0.0, 0.0))
            per_student[student_id] = (weighted + weight * score, total + weight)
            topic_scores[topic_id].append(score)
            topic_meta[topic_id] = (code, title)

    # Direction for every learner from one history query, not one per learner.
    series: dict[int, list[float]] = defaultdict(list)
    if member_ids:
        for student_id, score in (
            await db.execute(
                select(ReadinessHistory.student_id, ReadinessHistory.score)
                .where(
                    ReadinessHistory.student_id.in_(member_ids),
                    ReadinessHistory.subject_id == group.subject_id,
                )
                .order_by(ReadinessHistory.recorded_at)
            )
        ).all():
            series[student_id].append(score)

    learners: list[ClassLearnerRow] = []
    for student_id in member_ids:
        weighted, total = per_student.get(student_id, (0.0, 0.0))
        if not total:
            continue  # no confident evidence — absent, never a fabricated zero
        score = round(weighted / total, 1)
        grade = predict_grade(score, boundaries) if boundaries else None
        learners.append(
            ClassLearnerRow(
                student_id=student_id,
                student_name=names.get(student_id, "?"),
                score=score,
                predicted_grade=grade,
                status=grade_band(grade, boundaries),
                direction=trend_direction(series.get(student_id, [])),
            )
        )
    learners.sort(key=lambda r: r.score if r.score is not None else 0.0)

    weak_topics = sorted(
        (
            ClassWeakTopic(
                topic_code=topic_meta[tid][0],
                topic_title=topic_meta[tid][1],
                avg_score=round(sum(scores) / len(scores), 1),
                student_count=len(scores),
            )
            for tid, scores in topic_scores.items()
        ),
        key=lambda t: t.avg_score,
    )[:5]

    class_grade = (
        predict_grade(class_score, boundaries) if class_score is not None and boundaries else None
    )
    return ClassOverview(
        group_id=group.id,
        name=group.name,
        subject_name=group.subject.name if group.subject else "",
        score=class_score,
        predicted_grade=class_grade,
        status=grade_band(class_grade, boundaries),
        boundaries_missing=not boundaries,
        member_count=summary.member_count,
        students_with_evidence=summary.students_with_evidence,
        needs_you=[r for r in learners if r.direction == "down"],
        learners=learners,
        weak_topics=weak_topics,
    )
