"""A class's readiness picture, from Readiness Engine v2 (decisions 13, 15).

One definition, read by the tutor home strip and the class page
(services/today.py), the class cards' coverage count (services/groups.py) and
Group Analytics (api/analytics.py). Before 5.3a each of those aggregated v1
TopicReadiness rows its own way, and Group Analytics did it with a query per
learner — so the same class could carry three different scores (RISK-5, PERF-1).

The class score is the mean of each enrolled learner's **latest ready** v2
snapshot score — the same snapshot their own profile shows. A learner whose
latest run found no evidence is omitted and counted, never averaged in as 0
(PROD-2). The class page's own learner list is broader than that denominator,
though (fix round 1): every enrolled member gets a row there, unscored ones
sorted after scored ones by name, because a learner whose homework is marked
but whose run found no evidence still has a completion count to show (5.1,
AV-32) — and their profile already shows them. Everything here is a fixed
number of queries per call, whatever the roster size.
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiSynthesisStatus,
    FactorEvaluation,
    Group,
    GroupMember,
    ReadinessFactor,
    ReadinessSnapshot,
    Topic,
    User,
)
from app.services.readiness_shared import CONFIDENT


@dataclass(frozen=True)
class LearnerSnapshot:
    student_id: int
    student_name: str
    score: float | None  # None: the latest run found no evidence
    predicted_grade: str | None
    evaluation_run_id: str


@dataclass(frozen=True)
class TopicMean:
    topic_id: int
    topic_code: str
    topic_title: str
    avg_score: float
    student_count: int
    # True when any contributing learner's row rests on a tutor's estimate
    # rather than marked work alone — a class average can lean on one fresh
    # estimate same as an individual topic score can (fix round 1, PROD-8).
    includes_tutor_estimate: bool = False


@dataclass(frozen=True)
class ClassReadiness:
    score: float | None
    #: Scored learners only, lowest first — the class score's own denominator.
    scored: list[LearnerSnapshot]
    #: Every other enrolled learner, name order: a latest run that found no
    #: evidence (score None), or no snapshot yet. score and predicted_grade
    #: are always None here (PROD-2) — never a re-mapping of anything.
    unscored: list[LearnerSnapshot]
    #: Topic Mastery averaged over scored learners' latest runs, lowest first.
    topic_means: list[TopicMean]
    #: student_id -> (assignment_count, submitted_count) from every enrolled
    #: learner's latest ready run, scored or not — a no-evidence run still
    #: persists its own homework_performance row (readiness_summary_v2.py),
    #: so completion must not vanish with the headline score (AV-32).
    #: Absent = no homework row (never enrolled, or no run at all).
    homework: dict[int, tuple[int, int]]


async def latest_learner_snapshots(
    session: AsyncSession, group_ids: list[int]
) -> dict[int, dict[int, LearnerSnapshot]]:
    """Each enrolled learner's latest ready snapshot in their class's subject,
    for every given class, in one query.

    "Latest ready" is build_summary_v2's rule, deliberately: a failed synthesis
    is skipped, and a no-evidence run (ready, score None) *is* the latest — so
    a learner is never scored here while their profile says "not enough data
    yet". Partitioned by (group, student), not student alone: one student in
    two classes of different subjects has a different latest snapshot in each.
    SEC-7: group_ids arrive scoped to the authenticated tutor by every caller.
    """
    if not group_ids:
        return {}
    ranked = (
        select(
            GroupMember.group_id.label("group_id"),
            ReadinessSnapshot.student_id.label("student_id"),
            User.name.label("student_name"),
            ReadinessSnapshot.score.label("score"),
            ReadinessSnapshot.predicted_grade.label("predicted_grade"),
            ReadinessSnapshot.evaluation_run_id.label("run_id"),
            func.row_number()
            .over(
                partition_by=(GroupMember.group_id, ReadinessSnapshot.student_id),
                order_by=(ReadinessSnapshot.created_at.desc(), ReadinessSnapshot.id.desc()),
            )
            .label("rn"),
        )
        .select_from(GroupMember)
        .join(Group, Group.id == GroupMember.group_id)
        .join(User, User.id == GroupMember.student_id)
        .join(
            ReadinessSnapshot,
            (ReadinessSnapshot.student_id == GroupMember.student_id)
            # Subjects are org-owned (2.2), so the subject match is also what
            # keeps another subject's — or tenant's — score out of this class.
            & (ReadinessSnapshot.subject_id == Group.subject_id),
        )
        .where(
            GroupMember.group_id.in_(group_ids),
            ReadinessSnapshot.status == AiSynthesisStatus.ready,
        )
        .subquery()
    )
    out: dict[int, dict[int, LearnerSnapshot]] = {gid: {} for gid in group_ids}
    for row in (await session.execute(select(ranked).where(ranked.c.rn == 1))).all():
        out[row.group_id][row.student_id] = LearnerSnapshot(
            student_id=row.student_id,
            student_name=row.student_name,
            score=row.score,
            predicted_grade=row.predicted_grade,
            evaluation_run_id=row.run_id,
        )
    return out


def _mean(learners: dict[int, LearnerSnapshot]) -> tuple[float | None, int]:
    # Numerator and denominator from one filtered list — a None score is an
    # omitted learner, never a 0 in the average (PROD-2).
    scores = [s.score for s in learners.values() if s.score is not None]
    return (round(sum(scores) / len(scores), 1), len(scores)) if scores else (None, 0)


def class_scores(
    snapshots_by_group: dict[int, dict[int, LearnerSnapshot]],
) -> dict[int, tuple[float | None, int]]:
    """Fold an already-fetched latest_learner_snapshots() result into
    {group_id: (score, scored_count)} — class_health()'s shape, without
    re-running its query. For a caller that already needs the snapshots for
    another reason in the same request (services/today.py's build_today,
    which also feeds them to groups.summaries()) — calling class_health()
    there too would run the window query twice for the same group_ids."""
    return {gid: _mean(learners) for gid, learners in snapshots_by_group.items()}


async def class_health(
    session: AsyncSession, group_ids: list[int]
) -> dict[int, tuple[float | None, int]]:
    """{group_id: (class score or None, scored learner count)} for every class,
    in one query. (None, 0) for a class with nobody scored — never 0.0."""
    return class_scores(await latest_learner_snapshots(session, group_ids))


async def class_readiness(
    session: AsyncSession,
    group_id: int,
    learners: dict[int, LearnerSnapshot] | None = None,
) -> ClassReadiness:
    """The class page / Group Analytics detail: three queries, whatever the roster.

    `learners` is this group's entry from an already-run latest_learner_snapshots()
    — the class page needs it for groups.summaries() too, and the window query
    should run once per request, not once per consumer."""
    if learners is None:
        learners = (await latest_learner_snapshots(session, [group_id]))[group_id]
    score, _ = _mean(learners)
    scored = sorted(
        (s for s in learners.values() if s.score is not None), key=lambda s: s.score or 0.0
    )
    scored_ids = {s.student_id for s in scored}

    # Every enrolled learner, not just the ones with a scored run: a learner
    # whose latest run found no evidence, or who has no snapshot yet, still
    # belongs on the class page (fix round 1) — their homework completion is
    # independent of their score (5.1, AV-32) and their own profile already
    # shows them. One query, flat in roster size — rows grow, not queries.
    roster = (
        await session.execute(
            select(GroupMember.student_id, User.name)
            .join(User, User.id == GroupMember.student_id)
            .where(GroupMember.group_id == group_id)
        )
    ).all()
    unscored = sorted(
        (
            LearnerSnapshot(
                student_id=student_id,
                student_name=name,
                score=None,
                predicted_grade=None,
                evaluation_run_id=(
                    learners[student_id].evaluation_run_id if student_id in learners else ""
                ),
            )
            for student_id, name in roster
            if student_id not in scored_ids
        ),
        key=lambda s: s.student_name,
    )

    topic_scores: dict[int, list[float]] = defaultdict(list)
    meta: dict[int, tuple[str, str]] = {}
    includes_estimate: dict[int, bool] = defaultdict(bool)
    homework: dict[int, tuple[int, int]] = {}
    # Every learner with *any* ready run, scored or not — a no-evidence run
    # still persists its own homework_performance row, so a learner counted
    # under `unscored` above can still carry a completion count.
    run_ids = [s.evaluation_run_id for s in learners.values()]
    if run_ids:
        # Both factors from the learners' own latest runs in one statement —
        # an older run's topic score must not outvote the current one.
        rows = (
            await session.execute(
                select(
                    FactorEvaluation.student_id,
                    FactorEvaluation.factor,
                    FactorEvaluation.topic_id,
                    FactorEvaluation.score,
                    FactorEvaluation.confidence,
                    FactorEvaluation.detail,
                    Topic.code,
                    Topic.title,
                )
                .outerjoin(Topic, Topic.id == FactorEvaluation.topic_id)
                .where(
                    FactorEvaluation.evaluation_run_id.in_(run_ids),
                    FactorEvaluation.factor.in_(
                        (ReadinessFactor.topic_mastery, ReadinessFactor.homework_performance)
                    ),
                )
            )
        ).all()
        for r in rows:
            if r.factor == ReadinessFactor.homework_performance and r.topic_id is None:
                assigned = r.detail.get("assignment_count")
                submitted = r.detail.get("submitted_count")
                if assigned is not None and submitted is not None:
                    homework[r.student_id] = (assigned, submitted)
            elif (
                r.factor == ReadinessFactor.topic_mastery
                and r.topic_id is not None
                and r.score is not None
                and r.confidence in CONFIDENT
                # The outerjoin leaves code/title None for a topic_id that no
                # longer resolves — skip it rather than build a TopicMean with
                # no code, which `topic_code: str` (never optional) would 500 on.
                and r.code is not None
            ):
                topic_scores[r.topic_id].append(r.score)
                meta[r.topic_id] = (r.code, r.title)
                # One learner's row resting on an estimate is enough to label
                # the whole class mean — the average blends a real number in
                # (PROD-1), so the label travels with it (PROD-8), not just
                # with runs where every contributor is an estimate.
                if "tutor_estimate" in (r.detail or {}):
                    includes_estimate[r.topic_id] = True
    topic_means = sorted(
        (
            TopicMean(
                topic_id=tid,
                topic_code=meta[tid][0],
                topic_title=meta[tid][1],
                avg_score=round(sum(v) / len(v), 1),
                student_count=len(v),
                includes_tutor_estimate=includes_estimate[tid],
            )
            for tid, v in topic_scores.items()
        ),
        key=lambda t: t.avg_score,
    )
    return ClassReadiness(
        score=score, scored=scored, unscored=unscored, topic_means=topic_means, homework=homework
    )
