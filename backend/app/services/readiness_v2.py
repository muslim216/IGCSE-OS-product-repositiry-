"""Readiness Engine v2 — Layer 1 DB-facing orchestration.

Queries the DB, builds the plain dataclasses services/readiness_factors.py's
pure functions need, and persists one FactorEvaluation row per factor for a
(student, subject) computation run — topic-level for Topic Mastery,
subject-level for the other six. This module does no AI calls and is kept
out of any HTTP request path; it's only ever invoked from the
compute_readiness_v2 background job (Layer 2, services/readiness_v2_ai.py),
per the "run out-of-band" rule for deterministic computation.
"""

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assessment,
    AssessmentScore,
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    Evidence,
    FactorEvaluation,
    Group,
    GroupMember,
    Lesson,
    LessonTopic,
    Mistake,
    PastPaper,
    PastPaperAttempt,
    QuestionMark,
    QuestionTopic,
    ReadinessFactor,
    Submission,
    SubmissionStatus,
    Topic,
)
from app.services.readiness_factors import (
    AssessmentPoint,
    ConsistencyPoint,
    FactorResult,
    HomeworkPoint,
    MarkedQuestion,
    MistakePoint,
    PastPaperAttemptPoint,
    TopicCoverage,
    assessment_performance,
    consistency,
    homework_performance,
    mistake_analysis,
    past_paper_performance,
    syllabus_coverage,
    topic_mastery,
)

# A topic's Topic Mastery score at/above this is considered "mastered" for
# the Syllabus Coverage factor.
MASTERY_THRESHOLD = 75.0


def _factor_row(
    evaluation_run_id: str,
    student_id: int,
    subject_id: int,
    factor: ReadinessFactor,
    result: FactorResult,
    topic_id: int | None = None,
) -> FactorEvaluation:
    return FactorEvaluation(
        evaluation_run_id=evaluation_run_id,
        student_id=student_id,
        subject_id=subject_id,
        topic_id=topic_id,
        factor=factor,
        score=result.score,
        confidence=result.confidence,
        evidence_count=result.evidence_count,
        detail=result.detail,
    )


async def _marked_questions_for_topic(
    session: AsyncSession, student_id: int, topic_id: int
) -> list[MarkedQuestion]:
    rows = (
        await session.execute(
            select(QuestionMark, AssignmentQuestion, Submission)
            .join(AssignmentQuestion, AssignmentQuestion.id == QuestionMark.question_id)
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .join(QuestionTopic, QuestionTopic.question_id == AssignmentQuestion.id)
            .where(
                QuestionTopic.topic_id == topic_id,
                Submission.student_id == student_id,
                Submission.status == SubmissionStatus.finalized,
                QuestionMark.final_marks.is_not(None),
            )
        )
    ).all()
    out: list[MarkedQuestion] = []
    for mark, question, submission in rows:
        pct = (mark.final_marks / question.max_marks * 100) if question.max_marks else 0.0
        out.append(
            MarkedQuestion(
                difficulty=question.difficulty.value if question.difficulty else None,
                pct=pct,
                occurred_at=submission.finalized_at or submission.submitted_at,
            )
        )
    return out


async def _past_paper_attempts(
    session: AsyncSession, student_id: int, subject_id: int
) -> list[PastPaperAttemptPoint]:
    rows = (
        (
            await session.execute(
                select(PastPaperAttempt)
                .join(PastPaper, PastPaper.id == PastPaperAttempt.past_paper_id)
                .where(
                    PastPaper.subject_id == subject_id, PastPaperAttempt.student_id == student_id
                )
            )
        )
        .scalars()
        .all()
    )
    # An attempt with no usable marks is OMITTED, never scored (PROD-2, PROD-5).
    # `raw_marks` is null until the submission behind the attempt settles — the
    # model says so — so this is the ordinary state of work in progress, not an
    # edge case. Scoring it 0.0 would drag Past Paper Performance down for a
    # student whose paper simply has not been marked yet, and the factor cannot
    # tell a fabricated zero from an earned one. `max_marks` is NOT NULL, so the
    # zero-denominator guard is the genuinely exceptional half of this.
    return [
        PastPaperAttemptPoint(
            pct=a.raw_marks / a.max_marks * 100,
            timed=a.timed,
            attempted_at=a.attempted_at,
        )
        for a in rows
        if a.raw_marks is not None and a.max_marks
    ]


async def _homework_assignment_rows(session: AsyncSession, student_id: int, subject_id: int):
    return (
        await session.execute(
            select(Assignment, Submission)
            .join(Group, Group.id == Assignment.group_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .outerjoin(
                Submission,
                (Submission.assignment_id == Assignment.id) & (Submission.student_id == student_id),
            )
            .where(
                GroupMember.student_id == student_id,
                Group.subject_id == subject_id,
                Assignment.status.in_([AssignmentStatus.published, AssignmentStatus.closed]),
            )
        )
    ).all()


async def _homework_points(
    session: AsyncSession, student_id: int, subject_id: int
) -> list[HomeworkPoint]:
    rows = await _homework_assignment_rows(session, student_id, subject_id)
    points: list[HomeworkPoint] = []
    for assignment, submission in rows:
        if submission is None or submission.status != SubmissionStatus.finalized:
            points.append(HomeworkPoint(pct=None, on_time=None))
            continue
        marks = (
            await session.scalars(
                select(QuestionMark).where(QuestionMark.submission_id == submission.id)
            )
        ).all()
        total_max = (
            await session.scalar(
                select(func.coalesce(func.sum(AssignmentQuestion.max_marks), 0)).where(
                    AssignmentQuestion.assignment_id == assignment.id
                )
            )
        ) or 0
        total_final = sum(m.final_marks or 0 for m in marks)
        pct = (total_final / total_max * 100) if total_max else 0.0
        on_time = (
            submission.submitted_at <= assignment.due_at if assignment.due_at is not None else None
        )
        points.append(HomeworkPoint(pct=pct, on_time=on_time))
    return points


async def _consistency_points(
    session: AsyncSession, student_id: int, subject_id: int
) -> list[ConsistencyPoint]:
    rows = await _homework_assignment_rows(session, student_id, subject_id)
    return [
        ConsistencyPoint(
            due_at=assignment.due_at,
            submitted_at=submission.submitted_at if submission is not None else None,
        )
        for assignment, submission in rows
    ]


async def _assessment_points(
    session: AsyncSession, student_id: int, subject_id: int
) -> list[AssessmentPoint]:
    rows = (
        await session.execute(
            select(AssessmentScore, Assessment)
            .join(Assessment, Assessment.id == AssessmentScore.assessment_id)
            .where(AssessmentScore.student_id == student_id, Assessment.subject_id == subject_id)
        )
    ).all()
    return [
        AssessmentPoint(
            pct=(score.marks / score.max_marks * 100) if score.max_marks else 0.0,
            occurred_at=datetime(
                assessment.date.year,
                assessment.date.month,
                assessment.date.day,
                tzinfo=timezone.utc,
            ),
        )
        for score, assessment in rows
    ]


async def _topic_coverage(
    session: AsyncSession,
    student_id: int,
    subject_id: int,
    mastery_by_topic: dict[int, float | None],
    topics: Sequence[Topic],
) -> list[TopicCoverage]:
    topic_ids = {t.id for t in topics}

    taught_ids = set(
        (
            await session.scalars(
                select(LessonTopic.topic_id)
                .join(Lesson, Lesson.id == LessonTopic.lesson_id)
                .join(Group, Group.id == Lesson.group_id)
                .join(GroupMember, GroupMember.group_id == Group.id)
                .where(GroupMember.student_id == student_id, LessonTopic.topic_id.in_(topic_ids))
                .distinct()
            )
        ).all()
    )
    practiced_ids = set(
        (
            await session.scalars(
                select(Evidence.topic_id)
                .where(Evidence.student_id == student_id, Evidence.topic_id.in_(topic_ids))
                .distinct()
            )
        ).all()
    )

    return [
        TopicCoverage(
            taught=topic.id in taught_ids,
            practiced=topic.id in practiced_ids,
            mastered=(mastery_by_topic.get(topic.id) or 0) >= MASTERY_THRESHOLD,
        )
        for topic in topics
    ]


async def _mistake_points_and_total(
    session: AsyncSession, student_id: int, subject_id: int
) -> tuple[list[MistakePoint], int]:
    total_questions = (
        await session.scalar(
            select(func.count(QuestionMark.id))
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .join(Group, Group.id == Assignment.group_id)
            .where(
                Submission.student_id == student_id,
                Group.subject_id == subject_id,
                Submission.status == SubmissionStatus.finalized,
            )
        )
    ) or 0
    mistakes = (
        (
            await session.execute(
                select(Mistake)
                .join(QuestionMark, QuestionMark.id == Mistake.question_mark_id)
                .join(Submission, Submission.id == QuestionMark.submission_id)
                .join(Assignment, Assignment.id == Submission.assignment_id)
                .join(Group, Group.id == Assignment.group_id)
                .where(Mistake.student_id == student_id, Group.subject_id == subject_id)
            )
        )
        .scalars()
        .all()
    )
    points = [
        MistakePoint(category=m.category.value, severity=m.severity, occurred_at=m.created_at)
        for m in mistakes
    ]
    return points, total_questions


async def evaluate_subject_factors(
    session: AsyncSession,
    student_id: int,
    subject_id: int,
    evaluation_run_id: str,
    now: datetime | None = None,
) -> list[FactorEvaluation]:
    """Layer 1: compute every deterministic factor for one (student, subject)
    and persist one FactorEvaluation row per factor — topic-level rows for
    Topic Mastery, one subject-level row each for the rest. Returns the rows
    (already added to the session and flushed) for Layer 2 to read back."""
    now = now or datetime.now(timezone.utc)
    rows: list[FactorEvaluation] = []

    topics = (await session.scalars(select(Topic).where(Topic.subject_id == subject_id))).all()
    mastery_by_topic: dict[int, float | None] = {}
    for topic in topics:
        questions = await _marked_questions_for_topic(session, student_id, topic.id)
        result = topic_mastery(questions, now)
        mastery_by_topic[topic.id] = result.score
        rows.append(
            _factor_row(
                evaluation_run_id,
                student_id,
                subject_id,
                ReadinessFactor.topic_mastery,
                result,
                topic_id=topic.id,
            )
        )

    pp_result = past_paper_performance(await _past_paper_attempts(session, student_id, subject_id))
    rows.append(
        _factor_row(
            evaluation_run_id,
            student_id,
            subject_id,
            ReadinessFactor.past_paper_performance,
            pp_result,
        )
    )

    hw_result = homework_performance(await _homework_points(session, student_id, subject_id))
    rows.append(
        _factor_row(
            evaluation_run_id,
            student_id,
            subject_id,
            ReadinessFactor.homework_performance,
            hw_result,
        )
    )

    as_result = assessment_performance(
        await _assessment_points(session, student_id, subject_id), now
    )
    rows.append(
        _factor_row(
            evaluation_run_id,
            student_id,
            subject_id,
            ReadinessFactor.assessment_performance,
            as_result,
        )
    )

    coverage_result = syllabus_coverage(
        await _topic_coverage(session, student_id, subject_id, mastery_by_topic, topics)
    )
    rows.append(
        _factor_row(
            evaluation_run_id,
            student_id,
            subject_id,
            ReadinessFactor.syllabus_coverage,
            coverage_result,
        )
    )

    mistake_points, total_questions = await _mistake_points_and_total(
        session, student_id, subject_id
    )
    mistake_result = mistake_analysis(mistake_points, total_questions, now)
    rows.append(
        _factor_row(
            evaluation_run_id,
            student_id,
            subject_id,
            ReadinessFactor.mistake_analysis,
            mistake_result,
        )
    )

    consistency_result = consistency(await _consistency_points(session, student_id, subject_id))
    rows.append(
        _factor_row(
            evaluation_run_id,
            student_id,
            subject_id,
            ReadinessFactor.consistency,
            consistency_result,
        )
    )

    for row in rows:
        session.add(row)
    await session.flush()
    return rows
