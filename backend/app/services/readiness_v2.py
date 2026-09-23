"""Readiness Engine v2 — Layer 1 DB-facing orchestration.

Queries the DB, builds the plain dataclasses services/readiness_factors.py's
pure functions need, and persists one FactorEvaluation row per factor for a
(student, subject) computation run — topic-level for Topic Mastery,
subject-level for the other five. This module does no AI calls and is kept
out of any HTTP request path; it's only ever invoked from the
compute_readiness_v2 background job (Layer 2, services/readiness_v2_ai.py),
per the "run out-of-band" rule for deterministic computation.
"""

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    SETTLED_STATUSES,
    AssessableWork,
    Assessment,
    AssessmentScore,
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    Evidence,
    EvidenceSource,
    FactorEvaluation,
    Group,
    GroupMember,
    Lesson,
    LessonTopic,
    Mistake,
    MistakeCategory,
    PastPaper,
    PastPaperAttempt,
    QuestionMark,
    QuestionTopic,
    ReadinessFactor,
    Submission,
    Topic,
)
from app.services.readiness_factors import (
    AssessmentPoint,
    FactorResult,
    HomeworkPoint,
    MarkedQuestion,
    MistakePoint,
    PastPaperAttemptPoint,
    TopicCoverage,
    TutorEstimate,
    assessment_performance,
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
                Submission.status.in_(SETTLED_STATUSES),
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
                (Submission.work_id == Assignment.work_id) & (Submission.student_id == student_id),
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
        if submission is None or submission.status not in SETTLED_STATUSES:
            points.append(
                HomeworkPoint(
                    submitted=submission is not None,
                    pct=None,
                )
            )
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
        # Pre-existing: an assignment with no questions divides by zero here and
        # falls back to 0.0 rather than "no data" — a separate defect from this
        # change, left as-is (noted in the 5.1 PR).
        pct = (total_final / total_max * 100) if total_max else 0.0
        points.append(HomeworkPoint(submitted=True, pct=pct))
    return points


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
    # Owner decision (2026-09-23): coverage counts marked work only. A tutor's
    # estimate is their opinion entered before any work exists, not practice —
    # excluded here so "practised" never reads a self-declared score as
    # evidence the student has actually done anything (PROD-8). Homework,
    # mocks and observations still count.
    practiced_ids = set(
        (
            await session.scalars(
                select(Evidence.topic_id)
                .where(
                    Evidence.student_id == student_id,
                    Evidence.topic_id.in_(topic_ids),
                    Evidence.source_type != EvidenceSource.tutor_estimate,
                )
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


async def _mistake_points_and_analysed(
    session: AsyncSession, student_id: int, subject_id: int
) -> tuple[list[MistakePoint], int]:
    """Mistakes and the count of questions examined for them, across every kind
    of work.

    Joins AssessableWork, not Assignment. Both queries here used to inner-join
    Assignment for the subject, and Assignment.work_id is unique — so past
    paper and mock submissions were dropped from the mistake list *and* the
    denominator, with nothing to show for it (API-20). One parent row carries
    the subject for all three kinds, so there is no arm to forget.

    The denominator is gated on mistakes_analysed_at: a question only counts
    once the tag_mistakes job (4.2) has actually looked at it, not merely once
    it is marked — that gate is what stops an empty mistakes table reading as
    a clean record for work nobody has examined (PROD-2).

    **Deliberately not filtered on `Mistake.source`.** A mistake a tutor
    entered themselves counts exactly as one the tagging job proposed, because
    the tutor is the higher authority here, not the lower one (PROD-7) —
    filtering to `source="ai"` would drop precisely the observations somebody
    qualified made by hand. `source` exists so the job can replace its own rows
    without touching a tutor's (E17, decision 8); it is not a statement about
    what counts. Nothing writes `source="tutor"` until 4.3, so this is written
    down now, before the absence of a filter can be read as an oversight and
    "fixed".

    **Both queries carry the same gate, and must keep doing so.** They count
    two halves of one ratio, so a filter on one and not the other counts
    mistakes from questions the denominator does not count as examined. That is
    reachable today, not hypothetical: a remark request sets the whole
    submission back to `needs_review` (`api/submissions.py`), which leaves
    SETTLED_STATUSES while `mistakes_analysed_at` stays set and the Mistake rows
    stay put. Ungated, the numerator would keep summing them against a
    denominator that had dropped them — an understated score, no error, no log,
    self-correcting only whenever the tutor happens to re-finalize.
    """
    analysed_questions = (
        await session.scalar(
            select(func.count(QuestionMark.id))
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .join(AssessableWork, AssessableWork.id == Submission.work_id)
            .where(
                Submission.student_id == student_id,
                AssessableWork.subject_id == subject_id,
                Submission.status.in_(SETTLED_STATUSES),
                Submission.mistakes_analysed_at.is_not(None),
            )
        )
    ) or 0
    # The category name comes from a join, not `m.category.name` on a lazily
    # loaded relationship — that would be one query per row inside this loop,
    # a blocking call the worker's shared event loop cannot afford (BE-13,
    # PERF-1). Categories are tutor data (see MistakeCategory), so the name is
    # read here only to label the point, never branched on.
    mistakes = (
        await session.execute(
            select(Mistake, MistakeCategory.name)
            .join(QuestionMark, QuestionMark.id == Mistake.question_mark_id)
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .join(AssessableWork, AssessableWork.id == Submission.work_id)
            .join(MistakeCategory, MistakeCategory.id == Mistake.category_id)
            .where(
                Mistake.student_id == student_id,
                AssessableWork.subject_id == subject_id,
                Submission.status.in_(SETTLED_STATUSES),
                Submission.mistakes_analysed_at.is_not(None),
            )
        )
    ).all()
    points = [
        MistakePoint(category=category_name, severity=m.severity, occurred_at=m.created_at)
        for m, category_name in mistakes
    ]
    return points, analysed_questions


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
    # One query for every topic's estimate (PERF-1), not one per topic. Keyed
    # by topic_id: seed_readiness upserts on source_ref, so there is at most
    # one tutor_estimate row per (student, topic) for `.get` to find.
    estimates = {
        e.topic_id: TutorEstimate(pct=e.score_pct, occurred_at=e.occurred_at)
        for e in (
            await session.scalars(
                select(Evidence).where(
                    Evidence.student_id == student_id,
                    Evidence.source_type == EvidenceSource.tutor_estimate,
                    Evidence.topic_id.in_([t.id for t in topics] or [0]),
                )
            )
        ).all()
    }
    mastery_by_topic: dict[int, float | None] = {}
    for topic in topics:
        questions = await _marked_questions_for_topic(session, student_id, topic.id)
        result = topic_mastery(questions, now, estimate=estimates.get(topic.id))
        # An estimate alone never claims mastery for coverage (PROD-8): only a
        # score built from marked questions can mark a topic "mastered" below.
        mastery_by_topic[topic.id] = result.score if questions else None
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

    mistake_points, analysed_questions = await _mistake_points_and_analysed(
        session, student_id, subject_id
    )
    mistake_result = mistake_analysis(mistake_points, analysed_questions, now)
    rows.append(
        _factor_row(
            evaluation_run_id,
            student_id,
            subject_id,
            ReadinessFactor.mistake_analysis,
            mistake_result,
        )
    )

    for row in rows:
        session.add(row)
    await session.flush()
    return rows
