"""Integration test for Readiness Engine v2's Layer 1 gathering
(services/readiness_v2.evaluate_subject_factors): wires real DB rows through
every factor's DB-facing query and checks the resulting FactorEvaluation
rows, without touching the (still-live) v1 engine."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.models import (
    Assessment,
    AssessmentScore,
    AssessmentType,
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    Evidence,
    EvidenceSource,
    FactorEvaluation,
    Lesson,
    LessonTopic,
    Mistake,
    MistakeCategory,
    PastPaper,
    PastPaperAttempt,
    QuestionDifficulty,
    QuestionMark,
    QuestionTopic,
    ReadinessFactor,
    Submission,
    SubmissionStatus,
    User,
)
from app.services.readiness_v2 import evaluate_subject_factors
from tests.test_readiness_api import world  # noqa: F401 - shared fixture

NOW = datetime.now(timezone.utc)


async def test_evaluate_subject_factors_end_to_end(client, tutor, world):
    subject_id = world["subject_id"]
    student_id = world["student_id"]
    group_id = world["group"]["id"]
    topic1 = world["topic1"]

    async with async_session() as session:
        tutor_user = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        org_id = tutor_user.organization_id

        # Syllabus coverage input: a lesson covering topic1 only.
        lesson = Lesson(
            organization_id=org_id,
            group_id=group_id,
            date=date.today() - timedelta(days=10),
            duration_min=60,
        )
        session.add(lesson)
        await session.flush()
        session.add(LessonTopic(lesson_id=lesson.id, topic_id=topic1))

        # Practiced-but-not-via-homework evidence for topic1.
        session.add(
            Evidence(
                student_id=student_id,
                topic_id=topic1,
                source_type=EvidenceSource.observation,
                score_pct=60.0,
                max_marks=0,
                occurred_at=NOW - timedelta(days=3),
            )
        )

        # A finalized homework submission with one marked question on topic1.
        assignment = Assignment(
            group_id=group_id,
            title="HW1",
            status=AssignmentStatus.published,
            due_at=NOW - timedelta(days=2),
        )
        session.add(assignment)
        await session.flush()
        question = AssignmentQuestion(
            assignment_id=assignment.id,
            position=0,
            number="1",
            text_summary="Q1",
            max_marks=10,
            has_mark_scheme=True,
            difficulty=QuestionDifficulty.hard,
        )
        session.add(question)
        await session.flush()
        session.add(QuestionTopic(question_id=question.id, topic_id=topic1))

        submission = Submission(
            assignment_id=assignment.id,
            student_id=student_id,
            status=SubmissionStatus.finalized,
            submitted_at=NOW - timedelta(days=3),
            finalized_at=NOW - timedelta(days=1),
        )
        session.add(submission)
        await session.flush()
        mark = QuestionMark(
            submission_id=submission.id,
            question_id=question.id,
            final_marks=8,
        )
        session.add(mark)
        await session.flush()

        # A mistake tagged on that mark.
        session.add(
            Mistake(
                student_id=student_id,
                question_mark_id=mark.id,
                topic_id=topic1,
                category=MistakeCategory.careless,
                severity=1,
            )
        )

        # A past paper attempt for the subject.
        past_paper = PastPaper(
            organization_id=org_id,
            subject_id=subject_id,
            session_label="June 2026",
            paper_number="1",
        )
        session.add(past_paper)
        await session.flush()
        session.add(
            PastPaperAttempt(
                past_paper_id=past_paper.id,
                student_id=student_id,
                raw_marks=15,
                max_marks=20,
                timed=True,
                attempted_at=date.today() - timedelta(days=5),
            )
        )

        # A mock assessment score.
        assessment = Assessment(
            tutor_id=tutor_user.id,
            subject_id=subject_id,
            title="Mock",
            type=AssessmentType.mock,
            date=date.today() - timedelta(days=7),
        )
        session.add(assessment)
        await session.flush()
        session.add(
            AssessmentScore(
                assessment_id=assessment.id,
                student_id=student_id,
                topic_id=topic1,
                marks=14,
                max_marks=20,
            )
        )

        await session.commit()

    async with async_session() as session:
        rows = await evaluate_subject_factors(
            session, student_id, subject_id, "test-run-1", now=NOW
        )
        await session.commit()

    by_factor: dict[tuple, FactorEvaluation] = {(r.factor, r.topic_id): r for r in rows}

    topic1_mastery = by_factor[(ReadinessFactor.topic_mastery, topic1)]
    assert topic1_mastery.score == 80.0  # 8/10 marks
    assert topic1_mastery.detail["by_difficulty"] == {"hard": 80.0}

    topic2_mastery = by_factor[(ReadinessFactor.topic_mastery, world["topic2"])]
    assert topic2_mastery.score is None  # no marked questions for topic2

    pp = by_factor[(ReadinessFactor.past_paper_performance, None)]
    assert pp.score == 75.0  # 15/20
    assert pp.detail["timed_ratio"] == 1.0

    hw = by_factor[(ReadinessFactor.homework_performance, None)]
    assert hw.evidence_count == 1
    assert hw.detail["completion_rate"] == 1.0

    assess = by_factor[(ReadinessFactor.assessment_performance, None)]
    assert assess.score == 70.0  # 14/20

    coverage = by_factor[(ReadinessFactor.syllabus_coverage, None)]
    assert coverage.detail["topics_taught"] == 1
    assert coverage.detail["topics_practiced"] == 1  # topic1 has Evidence

    mistakes = by_factor[(ReadinessFactor.mistake_analysis, None)]
    assert mistakes.evidence_count == 1
    assert mistakes.detail["total_questions"] == 1
    assert mistakes.detail["by_category"] == {"careless": 1}

    cons = by_factor[(ReadinessFactor.consistency, None)]
    assert cons.detail["completion_rate"] == 1.0
    assert cons.detail["on_time_rate"] == 1.0  # submitted before due_at

    # Persisted rows are queryable back out — the append-only audit trail.
    async with async_session() as session:
        persisted = (
            await session.scalars(
                select(FactorEvaluation).where(FactorEvaluation.evaluation_run_id == "test-run-1")
            )
        ).all()
        assert len(persisted) == len(rows)
