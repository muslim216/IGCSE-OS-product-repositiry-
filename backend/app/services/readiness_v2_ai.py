"""Readiness Engine v2 — Layer 2: AI synthesis.

Takes the Layer 1 FactorEvaluation rows for one (student, subject) run (see
services/readiness_v2.py), the organization's ReadinessWeights, and the
tutor's Knowledge Base, and asks the AI to synthesize the final readiness
score, weak topics, rationale, and a revision plan.

Every ReadinessSnapshot carries the evaluation_run_id linking it back to the
exact FactorEvaluation rows it was built from. If the AI call fails, the
deterministic Layer 1 rows are still committed and a snapshot is still
written with status="failed" — the evaluation as a whole never silently
disappears, only the AI's contribution to it.

enqueue_v2_shadow() is how callers dual-run v2 alongside v1: it only
enqueues compute_readiness_v2 when settings.readiness_v2_shadow_enabled is
on, so v2 accumulates snapshots in the background for comparison without
affecting what any existing endpoint serves (see api/readiness_v2.py for the
read-only endpoints that expose them)."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    AiFeature,
    AiSynthesisStatus,
    FactorConfidence,
    FactorEvaluation,
    Group,
    GroupMember,
    Job,
    JobStatus,
    ReadinessFactor,
    ReadinessSnapshot,
    ReadinessWeights,
    Subject,
    Topic,
    User,
)
from app.services.ai import record_usage, structured_complete
from app.services.grade_boundaries import resolve_grade_boundaries
from app.services.grades import predict_grade
from app.services.knowledge import build_tutor_context, resolve_org_tutor_id
from app.services.readiness_v2 import evaluate_subject_factors
from app.workers.jobs import enqueue

log = logging.getLogger("readiness_v2_ai")

# resolve_grade_boundaries lives in services/grade_boundaries.py; it is imported
# here and re-exported so the existing readers that import it from this module
# keep working. Declared in __all__ so the re-export is intentional and a lint
# pass that strips "unused" imports cannot silently break those readers
# (CodeRabbit) — even though line 238 also uses it directly today.
__all__ = ["resolve_grade_boundaries"]


async def enqueue_readiness_v2_debounced(
    db: AsyncSession,
    student_id: int,
    subject_id: int | None = None,
    delay_seconds: int | None = None,
) -> None:
    """Schedule a v2 synthesis run for (student, subject), coalescing bursts.

    Synthesis is an expensive AI call and auto-marking can finalize a dozen
    submissions in seconds. If a run for the same (student, subject) is
    already queued, this is a no-op: that pending job reads live DB state when
    it fires, so it naturally covers everything that happened in the meantime.
    Otherwise a job is queued to run `delay_seconds` from now, so the whole
    burst costs one call instead of one per submission.
    """
    settings = get_settings()
    if not settings.readiness_v2_shadow_enabled:
        return
    payload = {"student_id": student_id, "subject_id": subject_id}
    # Compared in Python rather than SQL: the payload is a JSON column, and
    # Postgres' json type has no equality operator.
    pending = (
        await db.scalars(
            select(Job.payload).where(
                Job.type == "compute_readiness_v2",
                Job.status == JobStatus.pending,
            )
        )
    ).all()
    if any(
        p.get("student_id") == student_id and p.get("subject_id") == subject_id for p in pending
    ):
        return
    if delay_seconds is None:
        delay_seconds = settings.readiness_v2_coalesce_seconds
    await enqueue(
        db,
        "compute_readiness_v2",
        payload,
        run_after=datetime.now(timezone.utc) + timedelta(seconds=delay_seconds),
    )


async def enqueue_v2_shadow(
    db: AsyncSession, student_id: int, subject_id: int | None = None
) -> None:
    """Back-compatible alias for the debounced enqueue — every caller wants
    coalescing, so there is no un-debounced path."""
    await enqueue_readiness_v2_debounced(db, student_id, subject_id)


FACTOR_WEIGHT_ATTR = {
    ReadinessFactor.topic_mastery: "weight_topic_mastery",
    ReadinessFactor.past_paper_performance: "weight_past_paper_performance",
    ReadinessFactor.homework_performance: "weight_homework_performance",
    ReadinessFactor.assessment_performance: "weight_assessment_performance",
    ReadinessFactor.syllabus_coverage: "weight_syllabus_coverage",
    ReadinessFactor.mistake_analysis: "weight_mistake_analysis",
    ReadinessFactor.consistency: "weight_consistency",
}
DEFAULT_WEIGHTS = dict.fromkeys(FACTOR_WEIGHT_ATTR.values(), 1.0)

# Max points the AI's synthesized score may diverge from the weighted average
# of the deterministic factor scores before it is pulled back in line. The
# prompt tells the model the seven factor scores are "not permitted to
# contradict" — this is what makes that a constraint the code enforces,
# rather than only a request the model can ignore.
SCORE_CONTRADICTION_TOLERANCE = 10.0

# The prompt also tells the model a low-confidence factor should carry less
# weight than the raw number implies. A factor backed by only one or two
# marks isn't as trustworthy a veto over the AI's score as one backed by a
# term's worth of evidence, so the reference damps by whichever row within a
# factor has the weakest confidence. no_data is unreachable here (a None
# score is filtered out before this is consulted) but named for completeness.
CONFIDENCE_MULTIPLIER = {
    FactorConfidence.high: 1.0,
    FactorConfidence.medium: 0.7,
    FactorConfidence.low: 0.4,
    FactorConfidence.no_data: 0.0,
}
_CONFIDENCE_RANK = {
    FactorConfidence.no_data: 0,
    FactorConfidence.low: 1,
    FactorConfidence.medium: 2,
    FactorConfidence.high: 3,
}


def _weighted_reference_score(
    factor_rows: list[FactorEvaluation], weights: dict[str, float]
) -> float | None:
    """The deterministic answer, aggregated the way the prompt frames it to
    the model: one score per factor, not per row. evaluate_subject_factors()
    persists Topic Mastery as one row per topic but every other factor as a
    single subject-level row — averaging over rows unweighted would let Topic
    Mastery outvote the other six by however many topics the subject has.
    Collapsing to one mean score per factor first (and damping by that
    factor's weakest confidence) keeps the seven factors the prompt actually
    describes equally able to veto the AI's score, not "however many rows
    happen to exist".

    None when no factor has a score — that case never reaches synthesis (see
    the "no evidence" branch above), but this stays defensive rather than
    assuming that."""
    by_factor: dict[ReadinessFactor, list[FactorEvaluation]] = {}
    for row in factor_rows:
        if row.score is None:
            continue
        by_factor.setdefault(row.factor, []).append(row)

    total_weight = 0.0
    weighted_sum = 0.0
    for factor, rows in by_factor.items():
        factor_score = sum(row.score for row in rows if row.score is not None) / len(rows)
        weakest = min(rows, key=lambda row: _CONFIDENCE_RANK[row.confidence])
        weight = weights[FACTOR_WEIGHT_ATTR[factor]] * CONFIDENCE_MULTIPLIER[weakest.confidence]
        weighted_sum += factor_score * weight
        total_weight += weight
    return weighted_sum / total_weight if total_weight else None


def _enforce_factor_score_constraint(score: float, reference: float | None) -> float:
    """Pull the AI's score back to within SCORE_CONTRADICTION_TOLERANCE of the
    weighted factor reference. Correcting rather than rejecting: a tutor
    still gets a number today, just one Layer 1 can defend, instead of the
    run failing outright over a synthesis step that mostly got it right."""
    if reference is None:
        return score
    lower = reference - SCORE_CONTRADICTION_TOLERANCE
    upper = reference + SCORE_CONTRADICTION_TOLERANCE
    clamped = min(max(score, lower), upper)
    if clamped != score:
        log.warning(
            "readiness synthesis score %.1f contradicted the weighted factor "
            "reference %.1f by more than %.1f points; clamped to %.1f",
            score,
            reference,
            SCORE_CONTRADICTION_TOLERANCE,
            clamped,
        )
    return clamped


class WeakTopicSuggestion(BaseModel):
    topic_id: int = Field(description="Must be one of the topic ids in the Topic Mastery breakdown")
    reason: str = Field(description="Why this topic needs attention, from the data only")


class ReadinessSynthesis(BaseModel):
    score: float = Field(ge=0, le=100)
    weak_topics: list[WeakTopicSuggestion]
    rationale: str
    recommended_revision: str


async def _resolve_weight_dict(session: AsyncSession, organization_id: int) -> dict[str, float]:
    weights = await session.scalar(
        select(ReadinessWeights).where(ReadinessWeights.organization_id == organization_id)
    )
    if weights is None:
        return dict(DEFAULT_WEIGHTS)
    return {attr: getattr(weights, attr) for attr in DEFAULT_WEIGHTS}


# resolve_grade_boundaries used to live here, which put the precedence rule for
# every surface in the module that talks to a model. It now lives in
# services/grade_boundaries.py beside the writer that makes it reachable, and is
# re-exported so the existing readers keep their import.


def _factor_prompt_line(
    row: FactorEvaluation, weight: float, topics_by_id: dict[int, Topic]
) -> str:
    label = row.factor.value
    if row.topic_id is not None:
        topic = topics_by_id.get(row.topic_id)
        label = f"{label} ({topic.title if topic else row.topic_id})"
    score_text = f"{row.score:.1f}" if row.score is not None else "no data"
    return (
        f"- {label}: score={score_text}, confidence={row.confidence.value}, "
        f"evidence_count={row.evidence_count}, tutor_weight={weight}, detail={row.detail}"
    )


async def _synthesize_subject(
    session: AsyncSession, student: User, subject_id: int, now: datetime
) -> None:
    subject = await session.get(Subject, subject_id)
    if subject is None:
        return

    evaluation_run_id = str(uuid.uuid4())
    factor_rows = await evaluate_subject_factors(
        session, student.id, subject_id, evaluation_run_id, now
    )

    if all(row.score is None for row in factor_rows):
        session.add(
            ReadinessSnapshot(
                evaluation_run_id=evaluation_run_id,
                student_id=student.id,
                subject_id=subject_id,
                status=AiSynthesisStatus.ready,
                score=None,
                predicted_grade=None,
                weak_topics=[],
                rationale="No evidence yet for this subject.",
                recommended_revision=None,
            )
        )
        return

    weights = await _resolve_weight_dict(session, student.organization_id)
    topics = (await session.scalars(select(Topic).where(Topic.subject_id == subject_id))).all()
    topics_by_id = {t.id: t for t in topics}

    factors_text = "\n".join(
        _factor_prompt_line(row, weights[FACTOR_WEIGHT_ATTR[row.factor]], topics_by_id)
        for row in factor_rows
    )
    tutor_id = await resolve_org_tutor_id(session, student.organization_id)
    kb_context = (
        await build_tutor_context(session, tutor_id, subject_id) if tutor_id is not None else ""
    )

    prompt = (
        f"Student: {student.name}\n"
        f"Subject: {subject.name} ({subject.exam_board} {subject.code})\n\n"
        f"Factor sub-scores:\n{factors_text}\n\n"
        "Synthesize the overall readiness score, weak topics, rationale, and recommended revision."
    )

    try:
        response = await structured_complete(
            surface="readiness",
            content=[{"type": "text", "text": prompt}],
            output_format=ReadinessSynthesis,
            max_tokens=2000,
            extra_system=[kb_context] if kb_context else [],
        )
    except Exception as exc:  # noqa: BLE001 - AIUnavailableError or any API failure
        session.add(
            ReadinessSnapshot(
                evaluation_run_id=evaluation_run_id,
                student_id=student.id,
                subject_id=subject_id,
                status=AiSynthesisStatus.failed,
                score=None,
                predicted_grade=None,
                weak_topics=[],
                rationale=None,
                recommended_revision=None,
                error=str(exc) or exc.__class__.__name__,
            )
        )
        return

    if tutor_id is not None:
        await record_usage(
            session,
            response,
            organization_id=student.organization_id,
            tutor_id=tutor_id,
            student_id=student.id,
            feature=AiFeature.readiness,
        )
    result: ReadinessSynthesis = response.parsed
    reference_score = _weighted_reference_score(factor_rows, weights)
    score = _enforce_factor_score_constraint(result.score, reference_score)
    boundaries = await resolve_grade_boundaries(session, student.organization_id, subject)
    grade = predict_grade(score, boundaries)

    valid_topic_ids = {
        row.topic_id for row in factor_rows if row.factor == ReadinessFactor.topic_mastery
    }
    weak_topics = [
        {
            "topic_id": w.topic_id,
            "topic_title": topics_by_id[w.topic_id].title if w.topic_id in topics_by_id else None,
            "reason": w.reason,
        }
        for w in result.weak_topics
        if w.topic_id in valid_topic_ids
    ]

    session.add(
        ReadinessSnapshot(
            evaluation_run_id=evaluation_run_id,
            student_id=student.id,
            subject_id=subject_id,
            status=AiSynthesisStatus.ready,
            score=score,
            predicted_grade=grade,
            weak_topics=weak_topics,
            rationale=result.rationale,
            recommended_revision=result.recommended_revision,
        )
    )


async def compute_readiness_v2(session: AsyncSession, payload: dict) -> None:
    """Job handler. payload: {"student_id": int, "subject_id": int | None}.
    Omitting subject_id computes every subject the student is enrolled in."""
    student_id = payload["student_id"]
    subject_id = payload.get("subject_id")
    now = datetime.now(timezone.utc)

    student = await session.get(User, student_id)
    if student is None:
        return

    if subject_id is not None:
        subject_ids = [subject_id]
    else:
        subject_ids = list(
            (
                await session.scalars(
                    select(Group.subject_id)
                    .join(GroupMember, GroupMember.group_id == Group.id)
                    .where(GroupMember.student_id == student_id)
                    .distinct()
                )
            ).all()
        )

    for sid in subject_ids:
        await _synthesize_subject(session, student, sid, now)
    await session.commit()
