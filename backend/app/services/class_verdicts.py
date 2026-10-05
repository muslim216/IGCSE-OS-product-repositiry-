"""Per-class loader for the shared verdict (see student_verdict.py)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FactorEvaluation, Group, GroupMember, ReadinessFactor, Topic
from app.services.class_readiness import LearnerSnapshot, latest_learner_snapshots
from app.services.grade_boundaries import resolve_grade_boundaries
from app.services.readiness_config import resolve_readiness_config
from app.services.readiness_summary_v2 import weak_topic_rows
from app.services.student_verdict import Verdict, student_verdict


async def class_verdicts(
    db: AsyncSession,
    group: Group,
    snapshots: dict[int, LearnerSnapshot] | None = None,
) -> dict[int, Verdict]:
    """{student_id: Verdict} for every enrolled learner of one class, in a
    fixed number of queries whatever the roster (PERF-1). A learner with no
    ready snapshot gets "not_enough_data". Same inputs as the profile's
    summary — latest ready snapshot, the organization's boundaries, the
    resolved threshold — so the two cannot disagree. Called by the tutor's
    class page rows (services/today.py build_class_overview). SEC-7: the caller passes a
    group it has already scoped to the authenticated tutor. A caller that has
    already read the class's latest snapshots passes them, so the verdict and
    the row's score come from one read and cannot straddle a new run."""
    if snapshots is None:
        snapshots = (await latest_learner_snapshots(db, [group.id]))[group.id]
    roster = (
        await db.scalars(select(GroupMember.student_id).where(GroupMember.group_id == group.id))
    ).all()
    boundaries = await resolve_grade_boundaries(db, group.organization_id, group.subject)
    config = await resolve_readiness_config(db, group.organization_id, group.subject_id)

    rows_by_run: dict[str, list[FactorEvaluation]] = {}
    titles: dict[int, str] = {}
    run_ids = [s.evaluation_run_id for s in snapshots.values()]
    if run_ids:
        rows = (
            await db.scalars(
                select(FactorEvaluation).where(
                    FactorEvaluation.evaluation_run_id.in_(run_ids),
                    FactorEvaluation.factor == ReadinessFactor.topic_mastery,
                )
            )
        ).all()
        for r in rows:
            rows_by_run.setdefault(r.evaluation_run_id, []).append(r)
        titles = {
            t.id: t.title
            for t in await db.scalars(select(Topic).where(Topic.subject_id == group.subject_id))
        }

    out: dict[int, Verdict] = {}
    for student_id in roster:
        snap = snapshots.get(student_id)
        if snap is None:
            out[student_id] = student_verdict(
                score=None, predicted_grade=None, boundaries=boundaries, weak_topics=[]
            )
            continue
        # Rows for topics that still exist are filtered *before* the weak-topic
        # cap, as readiness_summary_v2 does, so a deleted topic cannot take one
        # of the places and make this list differ from the profile's.
        weak_rows = weak_topic_rows(
            [r for r in rows_by_run.get(snap.evaluation_run_id, []) if r.topic_id in titles],
            config.weak_threshold,
        )
        out[student_id] = student_verdict(
            score=snap.score,
            predicted_grade=snap.predicted_grade if boundaries else None,
            boundaries=boundaries,
            weak_topics=[titles[r.topic_id] for r in weak_rows if r.topic_id in titles],
        )
    return out
