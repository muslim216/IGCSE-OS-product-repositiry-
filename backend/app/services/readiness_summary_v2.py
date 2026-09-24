"""Serves the readiness UI/API from Readiness Engine v2.

v2 is the system of record for what the app shows: the latest ReadinessSnapshot
per subject supplies the overall score, predicted grade and weak topics, and
that run's topic_mastery FactorEvaluation rows supply the per-topic bars.

Two deliberate behaviours:

- **Fallback to v1, narrowed.** A subject with no ready snapshot yet (v2 never
  ran, or every run's AI synthesis failed) is shown with the no-snapshot shape
  below — never omitted, never a fabricated 0 (PROD-2). v1's
  services/readiness_summary.build_summary is consulted for that subject, but
  its answer is only used when v1 actually has a score: v1's tables are still
  maintained, so where it has a real number that number is served and
  labelled engine="v1" rather than the emptier no-snapshot shape. Where v1
  has nothing either, the no-snapshot shape stands. Phase 5.3b deletes this
  fallback once the post-deploy backfill (runbook R9) has run.
- **"Updating" is derived from the job queue, not the snapshot.** A
  ReadinessSnapshot row only exists once a run has finished, so there is no
  in-progress row to read. Instead a pending or running compute_readiness_v2
  job for that (student, subject) marks the summary is_updating, letting the UI
  say "recalculating" over the last known score instead of presenting a stale
  number as current.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiSynthesisStatus,
    FactorConfidence,
    FactorEvaluation,
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
from app.services.readiness_shared import (
    month_delta,
    scores_of,
    trend_direction,
    v2_score_points,
)
from app.services.readiness_summary import build_summary
from app.services.readiness_v2_ai import in_flight_readiness_pairs, resolve_grade_boundaries

# Job types whose presence means "a new score is on its way".
_IN_FLIGHT = (JobStatus.pending, JobStatus.running)


async def latest_ready_snapshot(
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
    pairs = await in_flight_readiness_pairs(db, _IN_FLIGHT)
    all_subjects = False
    subject_ids: set[int] = set()
    for pair_student_id, subject_id in pairs:
        if pair_student_id != student_id:
            continue
        if subject_id is None:
            all_subjects = True
        else:
            subject_ids.add(subject_id)
    return all_subjects, subject_ids


async def _subject_from_snapshot(
    db: AsyncSession, student: User, subject: Subject, snapshot: ReadinessSnapshot
) -> SubjectReadiness:
    """Per-topic bars and homework completion both come from the same
    evaluation run the snapshot was synthesized from, so the breakdown always
    matches the headline score — one query, not two, for the two factors this
    surface reads."""
    factor_rows = (
        await db.scalars(
            select(FactorEvaluation).where(
                FactorEvaluation.evaluation_run_id == snapshot.evaluation_run_id,
                FactorEvaluation.factor.in_(
                    (ReadinessFactor.topic_mastery, ReadinessFactor.homework_performance)
                ),
            )
        )
    ).all()
    rows = [
        r
        for r in factor_rows
        if r.factor == ReadinessFactor.topic_mastery and r.topic_id is not None
    ]
    # The homework_performance row is subject-level (topic_id IS NULL) and
    # always exists for a v2-computed run — even the "no evidence yet" run
    # (readiness_v2_ai.py ~:288) persists it before checking whether every
    # factor came back with no score, so completion is a fact this profile can
    # show even when the headline score itself is absent (PROD-2).
    homework_row = next(
        (
            r
            for r in factor_rows
            if r.factor == ReadinessFactor.homework_performance and r.topic_id is None
        ),
        None,
    )
    homework_detail = homework_row.detail if homework_row is not None else {}
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
            tutor_estimate="tutor_estimate" in (row.detail or {}),
        )
        for row in rows
        # A factor with no evidence reports "no data" — never a fabricated 0.
        if row.topic_id in topics
        and row.score is not None
        and row.confidence != FactorConfidence.no_data
    ]
    topic_out.sort(key=lambda t: t.topic_code)
    # One lookup, shared by score and the label below — an AI-picked weak
    # topic can be estimate-only at confidence `low` (fix round 1), and the
    # chip has to say so exactly when the matching topic row does.
    topic_out_by_id = {t.topic_id: t for t in topic_out}

    weak = [
        WeakTopic(
            topic_id=w["topic_id"],
            topic_code=topics[w["topic_id"]].code,
            topic_title=topics[w["topic_id"]].title,
            score=topic_out_by_id[w["topic_id"]].score if w["topic_id"] in topic_out_by_id else 0.0,
            tutor_estimate=(
                topic_out_by_id[w["topic_id"]].tutor_estimate
                if w["topic_id"] in topic_out_by_id
                else False
            ),
        )
        for w in snapshot.weak_topics
        if isinstance(w, dict) and w.get("topic_id") in topics
    ]

    # Band and averaging both map through the same list the snapshot's
    # predicted_grade was built from at synthesis time. Since task 2.4 (AV-11)
    # that is the only list there is — the global Subject.grade_boundaries column
    # is gone, closing the half of RISK-5 where two sources disagreed about one
    # subject's cut-offs. The half that remains is the v1/v2 engines answering
    # different surfaces, which is not this.
    #
    # Reading a *different* list would still be a different band, not a rounding
    # difference: nothing constrains one org's grade_label set to another's, and
    # [9, 7, 4, U] puts "4" at index 2 where a ten-grade list puts it at index 5.
    # Predicted-beside-averaging only means something if both used the same one.
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
        # A snapshot keeps the grade it was synthesized with, but the surface
        # only shows one while the organization still has boundaries to stand
        # behind it: clearing them means there is nothing the grade maps
        # through any more, and a stale one on screen is exactly the number
        # PROD-2 forbids. The stored value is untouched — it is the honest
        # record of what the engine said — and comes back if they set
        # boundaries again.
        predicted_grade=snapshot.predicted_grade if boundaries else None,
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
        # topic_out is already filtered to factors that had evidence; the
        # denominator is every topic in the subject, evidence or not. A tutor's
        # estimate adds one to evidence_count but is not practice (owner,
        # 2026-09-23), so an estimate-only topic is not counted as covered.
        topics_with_evidence=sum(
            1 for t in topic_out if t.evidence_count > (1 if t.tutor_estimate else 0)
        ),
        topic_count=len(topics),
        # A missing key means the run had no homework evidence to count, not
        # a rate of 0 — `homework_performance()`'s detail always carries both
        # keys once any assignment exists, so `.get` only returns None here
        # when the row itself is absent or genuinely has neither (PROD-2).
        homework_assignment_count=homework_detail.get("assignment_count"),
        homework_submitted_count=homework_detail.get("submitted_count"),
        topics=topic_out,
        weak_topics=weak[:5],
        rationale=snapshot.rationale,
        recommended_revision=snapshot.recommended_revision,
    )


async def _subject_without_snapshot(
    db: AsyncSession, student: User, subject: Subject
) -> SubjectReadiness:
    """No ready snapshot yet: v2 never ran for this subject, or every run's AI
    synthesis failed. The subject is still shown — as "not enough data yet",
    never omitted and never a 0 (PROD-2). Marked-work averaging is real data
    that does not depend on either engine, so it is still reported (PROD-1)."""
    topic_count = (
        await db.scalar(select(func.count(Topic.id)).where(Topic.subject_id == subject.id))
    ) or 0
    boundaries = await resolve_grade_boundaries(db, student.organization_id, subject)
    averaging = await subject_averaging(db, student.id, subject.id)
    return SubjectReadiness(
        subject_id=subject.id,
        subject_name=subject.name,
        exam_board=subject.exam_board,
        grade_scale=subject.grade_scale,
        score=None,
        predicted_grade=None,
        status=None,
        averaging_score=averaging.score,
        averaging_grade=(
            predict_grade(averaging.score, boundaries)
            if averaging.score is not None and boundaries
            else None
        ),
        marked_piece_count=averaging.marked_piece_count,
        topic_count=topic_count,
        topics=[],
        weak_topics=[],
    )


async def build_summary_v2(
    db: AsyncSession, student: User, subject_ids: list[int]
) -> StudentReadinessSummary:
    # A duplicated id would otherwise produce two SubjectReadiness entries for
    # the same subject; `position` below assumes one entry per id, and a
    # second entry for the same subject would silently survive the v1
    # fallback's overwrite. De-duplicated here, order preserved, so the same
    # list drives both the loop and the final sort.
    subject_ids = list(dict.fromkeys(subject_ids))
    everything_updating, updating = await in_flight_subjects(db, student.id)

    subjects_out: list[SubjectReadiness] = []
    without_snapshot: list[int] = []
    for subject_id in subject_ids:
        subject = await db.get(Subject, subject_id)
        if subject is None:
            continue
        snapshot = await latest_ready_snapshot(db, student.id, subject_id)
        if snapshot is None:
            out = await _subject_without_snapshot(db, student, subject)
            without_snapshot.append(subject_id)
        else:
            out = await _subject_from_snapshot(db, student, subject, snapshot)
            out.computed_at = snapshot.created_at
        out.is_updating = everything_updating or subject_id in updating
        subjects_out.append(out)

    if without_snapshot:
        # Until 5.3b: v1 still writes, so where it has a real score for a
        # subject v2 has not answered yet, that number is served and labelled
        # engine="v1". Where v1 has nothing either, the v2 no-snapshot shape
        # above stands — which is exactly what every subject gets once 5.3b
        # deletes these lines.
        position = {s.subject_id: i for i, s in enumerate(subjects_out)}
        legacy = await build_summary(db, student, without_snapshot)
        for legacy_subject in legacy.subjects:
            if legacy_subject.score is None:
                continue
            legacy_subject.engine = "v1"
            legacy_subject.is_updating = subjects_out[
                position[legacy_subject.subject_id]
            ].is_updating
            subjects_out[position[legacy_subject.subject_id]] = legacy_subject

    subjects_out.sort(key=lambda s: subject_ids.index(s.subject_id))
    return StudentReadinessSummary(
        student_id=student.id, student_name=student.name, subjects=subjects_out
    )


async def topic_mastery_row(
    db: AsyncSession, snapshot: ReadinessSnapshot, topic_id: int
) -> FactorEvaluation | None:
    """One topic's Topic Mastery row from the run a snapshot was built from —
    so the drill-down header is the same number as the topic's bar."""
    return await db.scalar(
        select(FactorEvaluation).where(
            FactorEvaluation.evaluation_run_id == snapshot.evaluation_run_id,
            FactorEvaluation.factor == ReadinessFactor.topic_mastery,
            FactorEvaluation.topic_id == topic_id,
        )
    )
