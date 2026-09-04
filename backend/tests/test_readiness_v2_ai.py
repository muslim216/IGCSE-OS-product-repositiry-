"""Readiness Engine v2 — Layer 2 (AI synthesis) job handler tests."""

from datetime import date

from sqlalchemy import select

from app.db import async_session
from app.models import (
    AiSynthesisStatus,
    Assessment,
    AssessmentScore,
    AssessmentType,
    FactorConfidence,
    FactorEvaluation,
    ReadinessFactor,
    ReadinessSnapshot,
    Subject,
    User,
)
from app.services.readiness_v2_ai import (
    DEFAULT_WEIGHTS,
    ReadinessSynthesis,
    WeakTopicSuggestion,
    _weighted_reference_score,
    compute_readiness_v2,
)
from tests.factories import subject_defaults
from tests.test_readiness_api import world  # noqa: F401 - shared fixture


def _row(factor, score, confidence=FactorConfidence.high):
    """An in-memory FactorEvaluation — never added to a session. The function
    under test only reads .factor/.score/.confidence, so this is enough to
    unit-test it without touching the database."""
    return FactorEvaluation(
        evaluation_run_id="test",
        student_id=1,
        subject_id=1,
        factor=factor,
        score=score,
        confidence=confidence,
    )


def test_weighted_reference_score_averages_per_factor_not_per_row():
    """Regression for the bug Qodo caught: Topic Mastery is persisted as one
    row per topic while every other factor gets exactly one row, so an
    unweighted average over rows let Topic Mastery outvote the other six by
    however many topics the subject has. Five strong topic-mastery rows must
    not drown out one weak homework-performance row."""
    rows = [_row(ReadinessFactor.topic_mastery, 90.0) for _ in range(5)] + [
        _row(ReadinessFactor.homework_performance, 20.0)
    ]
    reference = _weighted_reference_score(rows, DEFAULT_WEIGHTS)
    # Per-factor: mean(topic_mastery)=90, homework_performance=20 -> (90+20)/2 = 55.
    # Per-row (the bug): (90*5 + 20) / 6 ≈ 78.3 — far higher, and it would grow
    # with topic count rather than staying anchored to two equal factors.
    assert reference == 55.0


def test_a_no_data_row_does_not_drag_a_factors_reference_down():
    """A factor with one scored row and one no-data row averages to the scored
    one, not to half of it. `sum(... if score is not None) / len(rows)` — the
    shape a type checker invites — reads 45.0 here, scoring the absent
    measurement as a zero (PROD-2)."""
    rows = [
        _row(ReadinessFactor.topic_mastery, 90.0),
        _row(ReadinessFactor.topic_mastery, None, FactorConfidence.no_data),
    ]
    assert _weighted_reference_score(rows, DEFAULT_WEIGHTS) == 90.0


def test_weighted_reference_score_damps_low_confidence_factors():
    """A factor backed by only one or two marks (low confidence) must not
    veto the AI's score as forcefully as a well-evidenced one at the same
    tutor weight."""
    high_confidence_low_score = _row(
        ReadinessFactor.assessment_performance, 0.0, FactorConfidence.high
    )
    low_confidence_high_score = _row(
        ReadinessFactor.homework_performance, 100.0, FactorConfidence.low
    )
    reference = _weighted_reference_score(
        [high_confidence_low_score, low_confidence_high_score], DEFAULT_WEIGHTS
    )
    # An unweighted average would land at 50. Damping the low-confidence row
    # (0.4x) against the high-confidence one (1.0x) must pull it below that,
    # toward the number backed by more evidence.
    assert reference < 50.0


async def test_no_topics_yields_ready_snapshot_with_no_score(client, tutor, world):
    # A subject with zero topics is the only case where every factor
    # (including Syllabus Coverage, which is otherwise always well-defined
    # once a subject has topics) reports "no data".
    async with async_session() as session:
        empty_subject = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4XX1",
            name="Empty Subject",
            grade_scale="9-1",
            grade_boundaries=[],
        )
        session.add(empty_subject)
        await session.commit()
        empty_subject_id = empty_subject.id

    async with async_session() as session:
        await compute_readiness_v2(
            session, {"student_id": world["student_id"], "subject_id": empty_subject_id}
        )

    async with async_session() as session:
        snapshot = (
            await session.scalars(
                select(ReadinessSnapshot).where(
                    ReadinessSnapshot.student_id == world["student_id"],
                    ReadinessSnapshot.subject_id == empty_subject_id,
                )
            )
        ).one()
        assert snapshot.status == AiSynthesisStatus.ready
        assert snapshot.score is None
        assert "No evidence" in snapshot.rationale

        # No AI call was needed, but the deterministic layer still ran: six
        # subject-level factors (no topics -> no per-topic mastery rows).
        factor_rows = (
            await session.scalars(
                select(FactorEvaluation).where(
                    FactorEvaluation.student_id == world["student_id"],
                    FactorEvaluation.subject_id == empty_subject_id,
                )
            )
        ).all()
        assert len(factor_rows) == 6
        assert all(r.score is None for r in factor_rows)


async def test_syllabus_coverage_alone_still_triggers_ai_synthesis(client, tutor, world):
    """A subject with topics but zero other evidence isn't "no data" —
    Syllabus Coverage legitimately reports 0% — so synthesis is attempted
    (and fails gracefully here, since no ANTHROPIC_API_KEY is configured)."""
    async with async_session() as session:
        await compute_readiness_v2(
            session, {"student_id": world["student_id"], "subject_id": world["subject_id"]}
        )

    async with async_session() as session:
        snapshot = (
            await session.scalars(
                select(ReadinessSnapshot).where(ReadinessSnapshot.student_id == world["student_id"])
            )
        ).one()
        assert snapshot.status == AiSynthesisStatus.failed
        assert "ANTHROPIC_API_KEY" in snapshot.error

        factor_rows = (
            await session.scalars(
                select(FactorEvaluation).where(FactorEvaluation.student_id == world["student_id"])
            )
        ).all()
        assert len(factor_rows) == 8  # 2 topics + 6 subject-level factors
        coverage_row = next(r for r in factor_rows if r.factor.value == "syllabus_coverage")
        assert coverage_row.score == 0.0


async def test_ai_unavailable_writes_failed_snapshot_but_keeps_factors(client, tutor, world):
    async with async_session() as session:
        tutor_user = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        assessment = Assessment(
            tutor_id=tutor_user.id,
            subject_id=world["subject_id"],
            title="Mock",
            type=AssessmentType.mock,
            date=date.today(),
        )
        session.add(assessment)
        await session.flush()
        session.add(
            AssessmentScore(
                assessment_id=assessment.id,
                student_id=world["student_id"],
                topic_id=world["topic1"],
                marks=15,
                max_marks=20,
            )
        )
        await session.commit()

    # No ANTHROPIC_API_KEY is configured in tests -> AIUnavailableError.
    async with async_session() as session:
        await compute_readiness_v2(
            session, {"student_id": world["student_id"], "subject_id": world["subject_id"]}
        )

    async with async_session() as session:
        snapshot = (
            await session.scalars(
                select(ReadinessSnapshot).where(ReadinessSnapshot.student_id == world["student_id"])
            )
        ).one()
        assert snapshot.status == AiSynthesisStatus.failed
        assert snapshot.score is None
        assert "ANTHROPIC_API_KEY" in snapshot.error

        # The deterministic Layer 1 rows are still there despite the AI failure.
        factor_rows = (
            await session.scalars(
                select(FactorEvaluation).where(FactorEvaluation.student_id == world["student_id"])
            )
        ).all()
        assessment_row = next(r for r in factor_rows if r.factor.value == "assessment_performance")
        assert assessment_row.score == 75.0  # 15/20


async def test_ai_synthesis_success_filters_invalid_weak_topics(
    client, tutor, world, monkeypatch, fake_ai
):
    async with async_session() as session:
        tutor_user = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        assessment = Assessment(
            tutor_id=tutor_user.id,
            subject_id=world["subject_id"],
            title="Mock",
            type=AssessmentType.mock,
            date=date.today(),
        )
        session.add(assessment)
        await session.flush()
        session.add(
            AssessmentScore(
                assessment_id=assessment.id,
                student_id=world["student_id"],
                topic_id=world["topic1"],
                marks=10,
                max_marks=20,
            )
        )
        await session.commit()

    # Close to the weighted factor reference (50.0 here — see the dedicated
    # score-enforcement tests below) so this test exercises only what it's
    # named for: weak-topic filtering, not the score-contradiction clamp.
    fake_result = ReadinessSynthesis(
        score=45.0,
        weak_topics=[
            WeakTopicSuggestion(topic_id=world["topic1"], reason="Low assessment score"),
            WeakTopicSuggestion(topic_id=999999, reason="Hallucinated topic that doesn't exist"),
        ],
        rationale="Assessment performance is the only signal so far and it's weak.",
        recommended_revision="Do another topic quiz and a past paper attempt.",
    )
    monkeypatch.setattr("app.services.readiness_v2_ai.structured_complete", fake_ai(fake_result))

    async with async_session() as session:
        await compute_readiness_v2(
            session, {"student_id": world["student_id"], "subject_id": world["subject_id"]}
        )

    async with async_session() as session:
        snapshot = (
            await session.scalars(
                select(ReadinessSnapshot).where(ReadinessSnapshot.student_id == world["student_id"])
            )
        ).one()
        assert snapshot.status == AiSynthesisStatus.ready
        assert snapshot.score == 45.0
        assert snapshot.predicted_grade is not None
        # The hallucinated topic_id (999999) must be filtered out.
        assert len(snapshot.weak_topics) == 1
        assert snapshot.weak_topics[0]["topic_id"] == world["topic1"]


async def test_compute_all_subjects_when_subject_id_omitted(client, tutor, world):
    async with async_session() as session:
        await compute_readiness_v2(session, {"student_id": world["student_id"]})

    async with async_session() as session:
        snapshots = (
            await session.scalars(
                select(ReadinessSnapshot).where(ReadinessSnapshot.student_id == world["student_id"])
            )
        ).all()
        assert {s.subject_id for s in snapshots} == {world["subject_id"]}


async def test_ai_score_is_clamped_when_it_contradicts_the_factors(
    client, tutor, world, monkeypatch, fake_ai
):
    """The prompt tells the model the seven factor scores are "not permitted
    to contradict" — this proves that's enforced in code, not just requested
    of the model. A wildly implausible score must not reach the tutor as-is."""
    async with async_session() as session:
        tutor_user = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        assessment = Assessment(
            tutor_id=tutor_user.id,
            subject_id=world["subject_id"],
            title="Mock",
            type=AssessmentType.mock,
            date=date.today(),
        )
        session.add(assessment)
        await session.flush()
        session.add(
            AssessmentScore(
                assessment_id=assessment.id,
                student_id=world["student_id"],
                topic_id=world["topic1"],
                marks=18,
                max_marks=20,
            )
        )
        await session.commit()

    # A student doing well by every measured factor; the AI proposes a score
    # that flatly contradicts them.
    fake_result = ReadinessSynthesis(
        score=5.0,
        weak_topics=[],
        rationale="Deliberately implausible for this test.",
        recommended_revision="N/A",
    )
    monkeypatch.setattr("app.services.readiness_v2_ai.structured_complete", fake_ai(fake_result))

    async with async_session() as session:
        await compute_readiness_v2(
            session, {"student_id": world["student_id"], "subject_id": world["subject_id"]}
        )

    async with async_session() as session:
        snapshot = (
            await session.scalars(
                select(ReadinessSnapshot).where(ReadinessSnapshot.student_id == world["student_id"])
            )
        ).one()
        factor_rows = (
            await session.scalars(
                select(FactorEvaluation).where(
                    FactorEvaluation.evaluation_run_id == snapshot.evaluation_run_id
                )
            )
        ).all()
        # Computed the same way the persisted score was — one vote per factor,
        # confidence-damped — rather than re-deriving the formula by hand and
        # risking the test drifting out of sync with it.
        reference = _weighted_reference_score(factor_rows, DEFAULT_WEIGHTS)

        assert snapshot.status == AiSynthesisStatus.ready
        assert snapshot.score != 5.0  # the contradicting score was not persisted as-is
        assert abs(snapshot.score - (reference - 10.0)) < 1e-6  # pulled to the tolerance edge
