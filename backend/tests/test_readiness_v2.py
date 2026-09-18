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
    Mock,
    MockQuestion,
    PastPaperAttempt,
    PastPaperQuestion,
    QuestionDifficulty,
    QuestionMark,
    QuestionTopic,
    ReadinessFactor,
    Submission,
    SubmissionStatus,
    User,
    WorkKind,
)
from app.services.readiness_factors import NO_DATA, mistake_analysis
from app.services.readiness_v2 import _mistake_points_and_analysed, evaluate_subject_factors
from app.services.work import create_work
from tests.factories import make_past_paper
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
        work = await create_work(
            session,
            kind=WorkKind.homework,
            organization_id=org_id,
            subject_id=subject_id,
            title="HW1",
        )
        assignment = Assignment(
            work_id=work.id,
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
            student_id=student_id,
            status=SubmissionStatus.finalized,
            submitted_at=NOW - timedelta(days=3),
            finalized_at=NOW - timedelta(days=1),
            # Without this the mistake factor's denominator is 0 and the
            # factor reads NO_DATA even though a Mistake row exists below
            # (Task 4.0: analysed_questions is gated on this column).
            mistakes_analysed_at=NOW - timedelta(days=1),
            work_id=assignment.work_id,
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
        past_paper = await make_past_paper(
            session,
            organization_id=org_id,
            subject_id=subject_id,
            session_label="June 2026",
            paper_number="1",
        )
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
    assert mistakes.detail["analysed_questions"] == 1
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


async def test_an_unmarked_past_paper_attempt_is_omitted_not_scored_zero(client, tutor, world):
    """PROD-2 / PROD-5: `raw_marks` is null until the submission behind the
    attempt settles, so an unmarked attempt is ordinary work in progress. It
    must not reach Past Paper Performance at all — scoring it 0.0 would report
    a student who has started a paper as having failed it, and the factor
    cannot tell a fabricated zero from an earned one.
    """
    subject_id = world["subject_id"]
    student_id = world["student_id"]

    async with async_session() as session:
        tutor_user = await session.get(User, tutor["user"]["id"])
        assert tutor_user is not None
        org_id = tutor_user.organization_id
        past_paper = await make_past_paper(
            session,
            organization_id=org_id,
            subject_id=subject_id,
            session_label="June 2027",
            paper_number="2",
        )
        session.add_all(
            [
                # Settled: 18/20 = 90%.
                PastPaperAttempt(
                    past_paper_id=past_paper.id,
                    student_id=student_id,
                    raw_marks=18,
                    max_marks=20,
                    timed=True,
                    attempted_at=date.today() - timedelta(days=3),
                ),
                # Sat, not marked yet.
                PastPaperAttempt(
                    past_paper_id=past_paper.id,
                    student_id=student_id,
                    raw_marks=None,
                    max_marks=20,
                    timed=True,
                    attempted_at=date.today() - timedelta(days=1),
                ),
            ]
        )
        await session.commit()

    async with async_session() as session:
        rows = await evaluate_subject_factors(
            session, student_id, subject_id, "test-run-unmarked", now=NOW
        )
        await session.commit()

    paper = next(r for r in rows if r.factor == ReadinessFactor.past_paper_performance)
    # One attempt counted, not two, and the average is the marked one alone.
    # Were the unmarked attempt scored 0.0, this would be 45.0 over 2 attempts.
    assert paper.evidence_count == 1
    assert paper.detail["attempt_count"] == 1
    assert paper.score == 90.0


async def test_auto_finalized_work_counts_in_every_factor(client, tutor, world):
    """AV-29: an auto-finalized submission is a settled outcome and must reach
    every factor that reads marks.

    Three gatherers here restated "settled" as `finalized` alone, so work the
    AI marked confidently against an official scheme — which needs no tutor and
    is already visible to the student — was silently dropped from Topic
    Mastery, counted as *not submitted* by Homework Performance, and left out
    of Mistake Analysis' denominator. The last is the worst of the three: the
    mistakes still counted, so the ratio was computed against a smaller total
    and overstated how often the student erred.
    """
    subject_id = world["subject_id"]
    student_id = world["student_id"]
    group_id = world["group"]["id"]
    topic1 = world["topic1"]

    async with async_session() as session:
        tutor_user = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        org_id = tutor_user.organization_id
        work = await create_work(
            session,
            kind=WorkKind.homework,
            organization_id=org_id,
            subject_id=subject_id,
            title="Auto-marked HW",
        )
        assignment = Assignment(
            work_id=work.id,
            group_id=group_id,
            title="Auto-marked HW",
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
            difficulty=QuestionDifficulty.medium,
        )
        session.add(question)
        await session.flush()
        session.add(QuestionTopic(question_id=question.id, topic_id=topic1))

        submission = Submission(
            student_id=student_id,
            # The AI marked every question confidently against an official
            # scheme. No tutor touched it, and none needs to (AI-11).
            status=SubmissionStatus.auto_finalized,
            submitted_at=NOW - timedelta(days=3),
            finalized_at=NOW - timedelta(days=1),
            # See the comment on the equivalent line above.
            mistakes_analysed_at=NOW - timedelta(days=1),
            work_id=assignment.work_id,
        )
        session.add(submission)
        await session.flush()
        mark = QuestionMark(
            submission_id=submission.id,
            question_id=question.id,
            final_marks=6,
        )
        session.add(mark)
        await session.flush()
        session.add(
            Mistake(
                student_id=student_id,
                question_mark_id=mark.id,
                topic_id=topic1,
                category=MistakeCategory.careless,
                severity=1,
            )
        )
        await session.commit()

    async with async_session() as session:
        rows = await evaluate_subject_factors(
            session, student_id, subject_id, "test-run-auto", now=NOW
        )
        await session.commit()

    by_factor: dict[tuple, FactorEvaluation] = {(r.factor, r.topic_id): r for r in rows}

    # Topic Mastery: 6/10 on the only marked question for this topic.
    mastery = by_factor[(ReadinessFactor.topic_mastery, topic1)]
    assert mastery.score == 60.0

    # Homework Performance: the piece counts as submitted and scored, not as
    # an outstanding assignment.
    homework = by_factor[(ReadinessFactor.homework_performance, None)]
    assert homework.evidence_count == 1
    assert homework.detail["completion_rate"] == 1.0

    # Mistake Analysis: the mistake and the question it came from are counted
    # against each other. A denominator of 0 here is the bug this test exists
    # to catch.
    mistakes = by_factor[(ReadinessFactor.mistake_analysis, None)]
    assert mistakes.evidence_count == 1
    assert mistakes.detail["analysed_questions"] == 1


async def _mock_submission_with_mistake(
    session,
    *,
    org_id: int,
    tutor_id: int,
    subject_id: int,
    student_id: int,
    status: SubmissionStatus = SubmissionStatus.finalized,
    analysed: bool = True,
) -> None:
    """A settled mock submission with one marked, analysed question and one
    mistake on it — the mock arm of the homework setup in
    test_evaluate_subject_factors_end_to_end above, built through
    services.work.create_work, the only sanctioned creation path."""
    work = await create_work(
        session,
        kind=WorkKind.mock,
        organization_id=org_id,
        subject_id=subject_id,
        title="Mock paper",
    )
    mock = Mock(
        work_id=work.id,
        organization_id=org_id,
        tutor_id=tutor_id,
        subject_id=subject_id,
        title="Mock paper",
        paper_path="mocks/paper.pdf",
        paper_name="paper.pdf",
        paper_mime="application/pdf",
    )
    session.add(mock)
    await session.flush()
    question = MockQuestion(
        mock_id=mock.id,
        position=0,
        number="1",
        text_summary="Q1",
        max_marks=10,
        has_mark_scheme=True,
    )
    session.add(question)
    await session.flush()

    submission = Submission(
        student_id=student_id,
        status=status,
        submitted_at=NOW - timedelta(days=3),
        finalized_at=NOW - timedelta(days=1),
        mistakes_analysed_at=(NOW - timedelta(days=1)) if analysed else None,
        work_id=work.id,
    )
    session.add(submission)
    await session.flush()
    mark = QuestionMark(
        submission_id=submission.id,
        mock_question_id=question.id,
        final_marks=6,
    )
    session.add(mark)
    await session.flush()
    session.add(
        Mistake(
            student_id=student_id,
            question_mark_id=mark.id,
            category=MistakeCategory.careless,
            severity=1,
        )
    )
    await session.commit()


async def test_mistake_factor_counts_mocks(client, tutor, world):
    """A mock's marked questions reach both the mistake list and the
    denominator. They did not before: both queries inner-joined Assignment,
    whose work_id is unique, so every non-homework submission was dropped in
    silence (API-20)."""
    subject_id = world["subject_id"]
    student_id = world["student_id"]

    async with async_session() as session:
        tutor_user = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        org_id = tutor_user.organization_id
        await _mock_submission_with_mistake(
            session,
            org_id=org_id,
            tutor_id=tutor_user.id,
            subject_id=subject_id,
            student_id=student_id,
        )

    async with async_session() as session:
        points, analysed = await _mistake_points_and_analysed(session, student_id, subject_id)

    assert analysed == 1
    assert len(points) == 1


async def test_marked_but_unexamined_work_is_no_data(client, tutor, world):
    """The bug this whole change exists for. Marked work that nothing has
    examined for mistakes must read as no data, not as a clean record — an
    empty mistakes table looks identical to a flawless student, and scoring it
    put a fabricated confident 100.0 into a weighted factor (PROD-2)."""
    subject_id = world["subject_id"]
    student_id = world["student_id"]

    async with async_session() as session:
        tutor_user = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        await _mock_submission_with_mistake(
            session,
            org_id=tutor_user.organization_id,
            tutor_id=tutor_user.id,
            subject_id=subject_id,
            student_id=student_id,
            analysed=False,
        )

    async with async_session() as session:
        points, analysed = await _mistake_points_and_analysed(session, student_id, subject_id)

    assert analysed == 0
    assert mistake_analysis(points, analysed, NOW) is NO_DATA


async def test_mistakes_leave_the_numerator_when_their_work_leaves_settled(client, tutor, world):
    """Numerator and denominator count one population, so they carry one gate.

    A remark request sets the whole submission back to `needs_review`
    (`api/submissions.py`), which drops its questions out of the denominator
    while `mistakes_analysed_at` stays set and the Mistake rows stay put.
    Ungated, the numerator would keep charging those mistakes against a
    denominator that no longer counts them — a quietly understated score."""
    subject_id = world["subject_id"]
    student_id = world["student_id"]

    async with async_session() as session:
        tutor_user = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        await _mock_submission_with_mistake(
            session,
            org_id=tutor_user.organization_id,
            tutor_id=tutor_user.id,
            subject_id=subject_id,
            student_id=student_id,
            status=SubmissionStatus.needs_review,
        )

    async with async_session() as session:
        points, analysed = await _mistake_points_and_analysed(session, student_id, subject_id)

    assert analysed == 0
    assert points == []


async def _past_paper_submission_with_mistake(
    session, *, org_id: int, subject_id: int, student_id: int
) -> None:
    """The past-paper arm of the same setup — one arm passing does not prove
    the other (API-20's failure class dropped both)."""
    past_paper = await make_past_paper(
        session,
        organization_id=org_id,
        subject_id=subject_id,
        session_label="Nov 2026",
        paper_number="9",
    )
    question = PastPaperQuestion(
        past_paper_id=past_paper.id,
        position=0,
        number="1",
        text_summary="Q1",
        max_marks=10,
    )
    session.add(question)
    await session.flush()

    submission = Submission(
        student_id=student_id,
        status=SubmissionStatus.finalized,
        submitted_at=NOW - timedelta(days=3),
        finalized_at=NOW - timedelta(days=1),
        mistakes_analysed_at=NOW - timedelta(days=1),
        work_id=past_paper.work_id,
    )
    session.add(submission)
    await session.flush()
    mark = QuestionMark(
        submission_id=submission.id,
        past_paper_question_id=question.id,
        final_marks=7,
    )
    session.add(mark)
    await session.flush()
    session.add(
        Mistake(
            student_id=student_id,
            question_mark_id=mark.id,
            category=MistakeCategory.careless,
            severity=1,
        )
    )
    await session.commit()


async def test_mistake_factor_counts_past_papers(client, tutor, world):
    """The past-paper sibling of test_mistake_factor_counts_mocks."""
    subject_id = world["subject_id"]
    student_id = world["student_id"]

    async with async_session() as session:
        tutor_user = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        org_id = tutor_user.organization_id
        await _past_paper_submission_with_mistake(
            session, org_id=org_id, subject_id=subject_id, student_id=student_id
        )

    async with async_session() as session:
        points, analysed = await _mistake_points_and_analysed(session, student_id, subject_id)

    assert analysed == 1
    assert len(points) == 1
