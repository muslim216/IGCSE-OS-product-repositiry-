"""Readiness Engine v2 — Layer 2 (AI synthesis) job handler tests."""

from datetime import date

from sqlalchemy import select

from app.db import async_session
from app.models import (
    AiSynthesisStatus,
    Assessment,
    AssessmentScore,
    AssessmentType,
    FactorEvaluation,
    ReadinessSnapshot,
    Subject,
    User,
)
from app.services.readiness_v2_ai import (
    ReadinessSynthesis,
    WeakTopicSuggestion,
    compute_readiness_v2,
)
from tests.test_readiness_api import world  # noqa: F401 - shared fixture


async def test_no_topics_yields_ready_snapshot_with_no_score(client, tutor, world):
    # A subject with zero topics is the only case where every factor
    # (including Syllabus Coverage, which is otherwise always well-defined
    # once a subject has topics) reports "no data".
    async with async_session() as session:
        empty_subject = Subject(
            exam_board="Edexcel IGCSE", code="4XX1", name="Empty Subject",
            grade_scale="9-1", grade_boundaries=[],
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
            tutor_id=tutor_user.id, subject_id=world["subject_id"], title="Mock",
            type=AssessmentType.mock, date=date.today(),
        )
        session.add(assessment)
        await session.flush()
        session.add(
            AssessmentScore(
                assessment_id=assessment.id, student_id=world["student_id"],
                topic_id=world["topic1"], marks=15, max_marks=20,
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
            tutor_id=tutor_user.id, subject_id=world["subject_id"], title="Mock",
            type=AssessmentType.mock, date=date.today(),
        )
        session.add(assessment)
        await session.flush()
        session.add(
            AssessmentScore(
                assessment_id=assessment.id, student_id=world["student_id"],
                topic_id=world["topic1"], marks=10, max_marks=20,
            )
        )
        await session.commit()

    fake_result = ReadinessSynthesis(
        score=62.5,
        weak_topics=[
            WeakTopicSuggestion(topic_id=world["topic1"], reason="Low assessment score"),
            WeakTopicSuggestion(topic_id=999999, reason="Hallucinated topic that doesn't exist"),
        ],
        rationale="Assessment performance is the only signal so far and it's middling.",
        recommended_revision="Do another topic quiz and a past paper attempt.",
    )
    monkeypatch.setattr(
        "app.services.readiness_v2_ai.structured_complete", fake_ai(fake_result)
    )

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
        assert snapshot.score == 62.5
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
