"""Serves the readiness UI/API from Readiness Engine v2.

v2 is the system of record for what the app shows: the latest ReadinessSnapshot
per subject supplies the overall score, predicted grade and weak topics, and
that run's topic_mastery FactorEvaluation rows supply the per-topic bars.

Two deliberate behaviours:

- **Fallback to v1.** A student with no ready snapshot yet (v2 never ran, or
  its AI synthesis failed) falls back to services/readiness_summary.build_summary
  rather than showing an empty page. v1's tables are still maintained, so the
  fallback is real data, not a placeholder. This is what makes the cutover safe
  to ship before every student has been recomputed.
- **"Updating" is derived from the job queue, not the snapshot.** A
  ReadinessSnapshot row only exists once a run has finished, so there is no
  in-progress row to read. Instead a pending or running compute_readiness_v2
  job for that (student, subject) marks the summary is_updating, letting the UI
  say "recalculating" over the last known score instead of presenting a stale
  number as current.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiSynthesisStatus,
    FactorConfidence,
    FactorEvaluation,
    Job,
    JobStatus,
    ReadinessFactor,
    ReadinessSnapshot,
    Subject,
    Topic,
    User,
)
from app.schemas.readiness import (
    StudentReadinessSummary,
    SubjectReadiness,
    TopicReadinessOut,
    WeakTopic,
)
from app.services.averaging import subject_averaging
from app.services.grades import grade_band, predict_grade
from app.services.readiness_summary import (
    build_summary,
    month_delta,
    scores_of,
    trend_direction,
    v2_score_points,
)
from app.services.readiness_v2_ai import resolve_grade_boundaries

# Job types whose presence means "a new score is on its way".
_IN_FLIGHT = (JobStatus.pending, JobStatus.running)


async def _latest_ready_snapshot(
    db: AsyncSession, student_id: int, subject_id: int
) -> ReadinessSnapshot | None:
    return await db.scalar(
        select(ReadinessSnapshot)
        .where(
            ReadinessSnapshot.student_id == student_id,
            ReadinessSnapshot.subject_id == subject_id,
            ReadinessSnapshot.status == AiSynthesisStatus.ready,
        )
        .order_by(ReadinessSnapshot.created_at.desc(), ReadinessSnapshot.id.desc())
        .limit(1)
    )


async def in_flight_subjects(db: AsyncSession, student_id: int) -> tuple[bool, set[int]]:
    """(all_subjects, specific_subject_ids) with a v2 synthesis queued or
    running for this student. A job with no subject_id recomputes every subject
    they are enrolled in, so it sets the first element."""
    payloads = (
        await db.scalars(
            select(Job.payload).where(
                Job.type == "compute_readiness_v2",
                Job.status.in_(_IN_FLIGHT),
            )
        )
    ).all()
    all_subjects = False
    subject_ids: set[int] = set()
    for payload in payloads:
        if payload.get("student_id") != student_id:
            continue
        subject_id = payload.get("subject_id")
        if subject_id is None:
            all_subjects = True
        else:
            subject_ids.add(subject_id)
    return all_subjects, subject_ids


async def _subject_from_snapshot(
    db: AsyncSession, student: User, subject: Subject, snapshot: ReadinessSnapshot
) -> SubjectReadiness:
    """Per-topic bars come from the same evaluation run the snapshot was
    synthesized from, so the breakdown always matches the headline score."""
    rows = (
        await db.scalars(
            select(FactorEvaluation).where(
                FactorEvaluation.evaluation_run_id == snapshot.evaluation_run_id,
                FactorEvaluation.factor == ReadinessFactor.topic_mastery,
                FactorEvaluation.topic_id.is_not(None),
            )
        )
    ).all()
    topics = {
        t.id: t
        for t in (await db.scalars(select(Topic).where(Topic.subject_id == subject.id))).all()
    }
    topic_out = [
        TopicReadinessOut(
            topic_id=row.topic_id,
            topic_code=topics[row.topic_id].code,
            topic_title=topics[row.topic_id].title,
            score=row.score,
            confidence=row.confidence.value,
            evidence_count=row.evidence_count,
        )
        for row in rows
        # A factor with no evidence reports "no data" — never a fabricated 0.
        if row.topic_id in topics
        and row.score is not None
        and row.confidence != FactorConfidence.no_data
    ]
    topic_out.sort(key=lambda t: t.topic_code)

    weak = [
        WeakTopic(
            topic_id=w["topic_id"],
            topic_code=topics[w["topic_id"]].code,
            topic_title=topics[w["topic_id"]].title,
            score=next(
                (t.score for t in topic_out if t.topic_id == w["topic_id"]),
                0.0,
            ),
        )
        for w in snapshot.weak_topics
        if isinstance(w, dict) and w.get("topic_id") in topics
    ]

    # Band and averaging both map through the boundaries this organization's
    # predicted grade was built from, not the global Subject default. The
    # snapshot's predicted_grade was mapped through resolve_grade_boundaries at
    # synthesis time, and nothing constrains an org's grade_label set to match
    # the subject's — an org list of [9, 7, 4, U] puts "4" at index 2 where the
    # subject's ten-grade list puts it at index 5. Reading the wrong list is a
    # different band, not a rounding difference, and predicted-beside-averaging
    # only means something if both used the same list. (RISK-5 proper — the two
    # sources disagreeing on cut-offs — is still open and out of scope here.)
    boundaries = await resolve_grade_boundaries(db, student.organization_id, subject)
    averaging = await subject_averaging(db, student.id, subject.id)
    averaging_grade = (
        predict_grade(averaging.score, boundaries) if averaging.score is not None else None
    )
    # One read of the series, feeding both the arrow and the month's movement.
    points = await v2_score_points(db, student.id, subject.id) if snapshot.score is not None else []

    return SubjectReadiness(
        subject_id=subject.id,
        subject_name=subject.name,
        exam_board=subject.exam_board,
        grade_scale=subject.grade_scale,
        score=snapshot.score,
        predicted_grade=snapshot.predicted_grade,
        status=grade_band(snapshot.predicted_grade, boundaries),
        averaging_score=averaging.score,
        averaging_grade=averaging_grade,
        marked_piece_count=averaging.marked_piece_count,
        # From the snapshot series this score belongs to, so the arrow and the
        # trend line are the same claim. A snapshot with no score is a
        # no-evidence run: it renders "not enough data yet" and must carry no
        # arrow, even when older scored snapshots exist (PROD-2).
        direction=trend_direction(scores_of(points)) if snapshot.score is not None else None,
        # And the month's movement from those same points, for the same reason.
        month_delta=month_delta(points) if snapshot.score is not None else None,
        # topic_out is already filtered to factors that had evidence, so its
        # length is the covered count; the denominator is every topic in the
        # subject, evidence or not.
        topics_with_evidence=len(topic_out),
        topic_count=len(topics),
        topics=topic_out,
        weak_topics=weak[:5],
        rationale=snapshot.rationale,
        recommended_revision=snapshot.recommended_revision,
    )


async def build_summary_v2(
    db: AsyncSession, student: User, subject_ids: list[int]
) -> StudentReadinessSummary:
    everything_updating, updating = await in_flight_subjects(db, student.id)

    subjects_out: list[SubjectReadiness] = []
    fallback_needed: list[int] = []
    for subject_id in subject_ids:
        subject = await db.get(Subject, subject_id)
        if subject is None:
            continue
        snapshot = await _latest_ready_snapshot(db, student.id, subject_id)
        if snapshot is None:
            fallback_needed.append(subject_id)
            continue
        out = await _subject_from_snapshot(db, student, subject, snapshot)
        out.is_updating = everything_updating or subject_id in updating
        out.computed_at = snapshot.created_at
        subjects_out.append(out)

    if fallback_needed:
        # No v2 result for these yet — serve v1's numbers rather than a blank
        # page, and say so, so the UI can be honest about which engine spoke.
        legacy = await build_summary(db, student, fallback_needed)
        for legacy_subject in legacy.subjects:
            legacy_subject.engine = "v1"
            legacy_subject.is_updating = (
                everything_updating or legacy_subject.subject_id in updating
            )
        subjects_out.extend(legacy.subjects)

    subjects_out.sort(key=lambda s: subject_ids.index(s.subject_id))
    return StudentReadinessSummary(
        student_id=student.id, student_name=student.name, subjects=subjects_out
    )
