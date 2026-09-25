"""The tutor home and class-page aggregates.

The orchestration lives here rather than in the router (BE-1, BE-2): api/today.py
is request/response wiring only. Everything below is built from a **bounded**
number of queries — the surface it replaces issued one analytics request per
class, each of which looped `db.get(User)` plus a readiness select per learner
(PERF-1).
"""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AssessableWork,
    Group,
    GroupMember,
    Organization,
    ScheduleSlot,
    Submission,
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
from app.services.class_readiness import class_readiness, class_scores, latest_learner_snapshots
from app.services.grade_boundaries import boundaries_for, org_boundaries
from app.services.grades import grade_band, predict_grade
from app.services.groups import review_queue_predicate
from app.services.groups import summaries as group_summaries
from app.services.readiness_shared import scores_of, trend_direction, v2_score_series
from app.services.timezones import effective_timezone, today_weekday

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


async def pending_review_count(db: AsyncSession, organization_id: int) -> int:
    """How many submissions the review queue would list for this tutor.

    Every kind of work counts here. Counting only through an inner join to
    Assignment — which is what services/groups.summaries() does, correctly, for
    its *per-class* number — silently drops every past paper and every mock, so
    the home could report a clear day while that work sat in the review queue
    (API-20).

    The predicate itself is review_queue's, shared rather than restated: this
    count is the headline the tutor clicks to reach that page, so any difference
    between them is visible as a wrong number (see review_queue_predicate).

    Since D4 that predicate reads the parent row's one `organization_id`, so
    counting needs the one join and none of the per-kind ones this used to
    carry — and a kind nobody joined can no longer go missing from the count.
    """
    return (
        await db.scalar(
            select(func.count(Submission.id))
            .join(AssessableWork, AssessableWork.id == Submission.work_id)
            .where(*review_queue_predicate(organization_id))
        )
    ) or 0


async def today_lessons(
    db: AsyncSession, tutor_id: int, organization_id: int, user_zone: str | None = None
) -> list[UpcomingScheduleSlot]:
    """The tutor's lessons for *their* today.

    This lives in the service layer because two routes need it — /me/today-lessons
    and the home aggregate — and a router must never call another router (BE-2).
    It previously did: api/today.py imported api/me.py's handler, so adding a
    dependency or a Query parameter to that route would have silently changed the
    aggregate, and the timezone rule below was a side effect of a route.
    """
    # "Today" is this person's today, not the server's. A tutor in Cairo opening
    # this at 01:00 local is on tomorrow's weekday while UTC is still on
    # yesterday's, and this answer is entirely *which day it is*.
    #
    # `user_zone` is their own override (AV-67) and wins over the organization's
    # when set — a tutor travelling has moved their own midnight, not the
    # account's. It defaults to None so a caller that has no user row still gets
    # the organization's answer rather than silently getting UTC.
    org = await db.get(Organization, organization_id)
    weekday = today_weekday(effective_timezone(user_zone, org.timezone if org else None))
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
    lessons = await today_lessons(db, user.id, user.organization_id, user.time_zone)
    groups = await tutor_groups(db, user.id)
    group_ids = [g.id for g in groups]
    # One latest-snapshot read feeds both the class cards' coverage count and
    # the strip's score. Calling class_health() here too would run this same
    # window query a second time for the same group_ids (fix round 1).
    snapshots = await latest_learner_snapshots(db, group_ids)
    summaries = await group_summaries(db, group_ids, snapshots_by_group=snapshots)
    health = class_scores(snapshots)
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

    Every enrolled learner appears under Learners (fix round 1), not only the
    scored ones: a learner whose latest run found no evidence, or who has none
    yet, is still listed — sorted after the scored learners, by name, with a
    null score/grade/arrow — because their homework completion can be real
    even when their score is not (5.1, AV-32), and hiding them entirely would
    make the roster undercount the class.

    Score, grade and arrow all come from the learner's own **v2** snapshot
    series (services/class_readiness.py) — the same series their own profile
    reads. Before 5.3a this surface answered from v1 (TopicReadiness,
    ReadinessHistory) while the student's own readiness answered from v2, so
    the two could disagree (RISK-5); that gap is closed here.
    """
    overrides = await org_boundaries(db, user.organization_id)
    boundaries = boundaries_for(overrides, group.subject)
    summary = (await group_summaries(db, [group.id]))[group.id]
    detail = await class_readiness(db, group.id)
    # Every scored learner's series in one query, not one per learner (PERF-1).
    # Unscored learners are never looked up here — their `series.get(...)`
    # below returns [] and trend_direction([]) is None, which is exactly what
    # they must show: no score means no arrow to describe (PROD-2).
    series = await v2_score_series(db, [s.student_id for s in detail.scored], group.subject_id)

    learners: list[ClassLearnerRow] = []
    for s in detail.scored + detail.unscored:
        # The snapshot's own grade — what the learner's profile prints — shown
        # only while boundaries exist to stand behind it (PROD-2). Always None
        # for an unscored learner: class_readiness() never sets one for them.
        grade = s.predicted_grade if boundaries else None
        hw = detail.homework.get(s.student_id)
        learners.append(
            ClassLearnerRow(
                student_id=s.student_id,
                student_name=s.student_name,
                score=s.score,
                predicted_grade=grade,
                status=grade_band(grade, boundaries),
                direction=trend_direction(scores_of(series.get(s.student_id, []))),
                homework_assignment_count=hw[0] if hw else None,
                homework_submitted_count=hw[1] if hw else None,
            )
        )

    class_grade = (
        predict_grade(detail.score, boundaries) if detail.score is not None and boundaries else None
    )
    return ClassOverview(
        group_id=group.id,
        name=group.name,
        subject_name=group.subject.name if group.subject else "",
        score=detail.score,
        predicted_grade=class_grade,
        status=grade_band(class_grade, boundaries),
        boundaries_missing=not boundaries,
        member_count=summary.member_count,
        students_with_evidence=summary.students_with_evidence,
        needs_you=[r for r in learners if r.direction == "down"],
        # Already ordered: scored learners lowest score first, then unscored
        # by name — class_readiness sorts each list this way.
        learners=learners,
        weak_topics=[
            ClassWeakTopic(
                topic_code=t.topic_code,
                topic_title=t.topic_title,
                avg_score=t.avg_score,
                student_count=t.student_count,
                includes_tutor_estimate=t.includes_tutor_estimate,
            )
            for t in detail.topic_means[:5]
        ],
    )
