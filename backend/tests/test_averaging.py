"""The averaging grade — the plain mean of a student's settled marked work.

Covers the two halves of services/averaging.py separately: the pure mean over
mark rows, and the query that decides which rows exist in the first place.
"""

import pytest

from app.db import async_session
from app.models import (
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    PastPaper,
    PastPaperQuestion,
    QuestionMark,
    Subject,
    Submission,
    SubmissionStatus,
    User,
)
from app.services.averaging import MarkRow, average_marked_work, subject_averaging

# ---- The pure mean ----


def test_pure_no_rows_returns_none():
    result = average_marked_work([])
    assert result.score is None
    assert result.marked_piece_count == 0


def test_pure_each_piece_counts_once_regardless_of_size():
    # One 100-mark piece at 50% and one 10-mark piece at 100%: the mean of the
    # two percentages is 75, not the 54.5 an aggregate marks-over-total gives.
    rows = [
        MarkRow(submission_id=1, final_marks=50, max_marks=100),
        MarkRow(submission_id=2, final_marks=10, max_marks=10),
    ]
    assert average_marked_work(rows).score == 75.0


def test_pure_questions_within_a_piece_aggregate():
    # A piece's own questions do sum — it is one piece scoring 15/20.
    rows = [
        MarkRow(submission_id=1, final_marks=8, max_marks=10),
        MarkRow(submission_id=1, final_marks=7, max_marks=10),
    ]
    result = average_marked_work(rows)
    assert result.score == 75.0
    assert result.marked_piece_count == 1


def test_pure_unmarked_question_excluded_not_zeroed():
    # 8/10 on the marked question; the blank one is absent evidence, not a zero.
    # Counting it would give 40% — a number the student never scored.
    rows = [
        MarkRow(submission_id=1, final_marks=8, max_marks=10),
        MarkRow(submission_id=1, final_marks=None, max_marks=10),
    ]
    assert average_marked_work(rows).score == 80.0


def test_pure_piece_with_no_marked_questions_does_not_count():
    rows = [MarkRow(submission_id=1, final_marks=None, max_marks=10)]
    result = average_marked_work(rows)
    assert result.score is None
    assert result.marked_piece_count == 0


# ---- The query ----


@pytest.fixture
async def world(client, tutor):
    """A subject, a group, and a student enrolled in it."""
    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4MA1",
            name="Maths",
            grade_scale="9-1",
            grade_boundaries=[
                {"grade": "9", "min": 90},
                {"grade": "7", "min": 70},
                {"grade": "4", "min": 40},
                {"grade": "U", "min": 0},
            ],
        )
        session.add(subject)
        await session.commit()
        subject_id = subject.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Set A", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    student = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Sara", "username": "sara01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()

    async with async_session() as session:
        org_id = (await session.get(User, student["id"])).organization_id

    return {
        "subject_id": subject_id,
        "group_id": group["id"],
        "student_id": student["id"],
        "org_id": org_id,
    }


async def add_homework(world, marks, *, status=SubmissionStatus.finalized, title="HW"):
    """A homework submission carrying one question per (final_marks, max_marks)
    pair in `marks`. A final_marks of None is a question left unmarked."""
    async with async_session() as session:
        assignment = Assignment(
            group_id=world["group_id"], title=title, status=AssignmentStatus.published
        )
        session.add(assignment)
        await session.flush()
        submission = Submission(
            assignment_id=assignment.id, student_id=world["student_id"], status=status
        )
        session.add(submission)
        await session.flush()
        for position, (final_marks, max_marks) in enumerate(marks):
            question = AssignmentQuestion(
                assignment_id=assignment.id,
                position=position,
                number=str(position + 1),
                text_summary="Q",
                max_marks=max_marks,
            )
            session.add(question)
            await session.flush()
            session.add(
                QuestionMark(
                    submission_id=submission.id,
                    question_id=question.id,
                    final_marks=final_marks,
                )
            )
        await session.commit()


async def add_past_paper(world, marks, *, status=SubmissionStatus.finalized):
    """The same, as a past paper: the submission's assignment_id stays None."""
    async with async_session() as session:
        paper = PastPaper(
            organization_id=world["org_id"],
            subject_id=world["subject_id"],
            session_label="June 2026",
            paper_number="1",
        )
        session.add(paper)
        await session.flush()
        submission = Submission(
            past_paper_id=paper.id, student_id=world["student_id"], status=status
        )
        session.add(submission)
        await session.flush()
        for position, (final_marks, max_marks) in enumerate(marks):
            question = PastPaperQuestion(
                past_paper_id=paper.id,
                position=position,
                number=str(position + 1),
                text_summary="Q",
                max_marks=max_marks,
            )
            session.add(question)
            await session.flush()
            session.add(
                QuestionMark(
                    submission_id=submission.id,
                    past_paper_question_id=question.id,
                    final_marks=final_marks,
                )
            )
        await session.commit()


async def averaging_for(world):
    async with async_session() as session:
        return await subject_averaging(session, world["student_id"], world["subject_id"])


async def test_no_marked_work_returns_none(client, tutor, world):
    result = await averaging_for(world)
    assert result.score is None
    assert result.marked_piece_count == 0


async def test_draft_marks_excluded(client, tutor, world):
    # Marks exist, but the submission is still in the tutor's queue. Nothing
    # provisional influences a grade a parent is shown (PROD-5).
    await add_homework(world, [(9, 10)], status=SubmissionStatus.ai_marked)
    await add_homework(world, [(5, 10)], status=SubmissionStatus.needs_review, title="HW2")
    result = await averaging_for(world)
    assert result.score is None
    assert result.marked_piece_count == 0


async def test_auto_finalized_work_counts(client, tutor, world):
    # The AI marked it confidently against an official scheme — settled, so it
    # counts without a tutor having touched it.
    await add_homework(world, [(9, 10)], status=SubmissionStatus.auto_finalized)
    assert (await averaging_for(world)).score == 90.0


async def test_past_paper_submission_contributes(client, tutor, world):
    # assignment_id is None on this submission; it must still be found, and
    # reading that column unconditionally would raise (API-20, PROD-9).
    await add_past_paper(world, [(12, 20)])
    result = await averaging_for(world)
    assert result.score == 60.0
    assert result.marked_piece_count == 1


async def test_homework_and_past_paper_average_together(client, tutor, world):
    await add_homework(world, [(8, 10)])  # 80%
    await add_past_paper(world, [(12, 20)])  # 60%
    result = await averaging_for(world)
    assert result.score == 70.0
    assert result.marked_piece_count == 2


async def test_unmarked_question_excluded_not_zeroed(client, tutor, world):
    # One question marked 8/10, one deliberately left blank. Counting the blank
    # would report 40% — a score the student never got (PROD-2).
    await add_homework(world, [(8, 10), (None, 10)])
    assert (await averaging_for(world)).score == 80.0


async def test_marked_piece_count_matches_contributing_rows(client, tutor, world):
    await add_homework(world, [(7, 10)], title="HW1")
    await add_homework(world, [(9, 10)], title="HW2")
    await add_homework(world, [(1, 10)], status=SubmissionStatus.ai_marked, title="HW3")
    result = await averaging_for(world)
    # Two settled pieces contributed; the draft is neither counted nor averaged.
    assert result.marked_piece_count == 2
    assert result.score == 80.0


async def test_other_subjects_do_not_contribute(client, tutor, world):
    """A second subject's marked work stays out of this subject's average."""
    async with async_session() as session:
        other = Subject(
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(other)
        await session.commit()
        other_subject_id = other.id

    other_group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": other_subject_id},
            headers=tutor["headers"],
        )
    ).json()

    await add_homework(world, [(8, 10)])
    await add_homework({**world, "group_id": other_group["id"]}, [(2, 10)], title="Chem HW")

    assert (await averaging_for(world)).score == 80.0
