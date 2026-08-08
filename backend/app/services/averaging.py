"""The averaging grade: the plain mean of a student's marked work in a subject.

Distinct from the *predicted* grade, and deliberately so. The predicted grade
comes from the readiness score — weighted and recency-aware, a claim about where
the student is heading. The averaging grade is backward-looking: what they have
actually been getting. Both map through the same boundaries, and the gap between
them is the story a student and a parent are shown (experience-design.md §3.3).

Only settled work counts (PROD-5): a submission is included once it is finalized
or auto-finalized, never while a mark is still a draft. Past papers contribute
through the same path as homework, because both are Submission + QuestionMark
rows (PROD-9, ADR-0004).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assignment,
    AssignmentQuestion,
    Group,
    PastPaper,
    PastPaperQuestion,
    QuestionMark,
    Submission,
    SubmissionStatus,
)

# A submission's marks count only once it has settled. An AI draft awaiting a
# tutor is not an outcome, and must not move a grade shown to a parent (PROD-5).
SETTLED = (SubmissionStatus.finalized, SubmissionStatus.auto_finalized)


@dataclass(frozen=True)
class MarkRow:
    """One marked question: which piece of work it belongs to, the mark the
    tutor settled on, and what the question was out of. final_marks is None for
    a question nobody has marked — carried through rather than filtered at the
    query, so the pure function below owns the rule about what that means."""

    submission_id: int
    final_marks: int | None
    max_marks: int


@dataclass(frozen=True)
class Averaging:
    """score is None when there is nothing to average — never 0, which would be
    a claim that the student scored nothing (PROD-2). marked_piece_count travels
    with the score so a surface can say what the value was computed from
    (PROD-1); it is the number of pieces that actually contributed, not the
    number submitted."""

    score: float | None
    marked_piece_count: int


def average_marked_work(rows: Sequence[MarkRow]) -> Averaging:
    """Mean of one percentage per piece of marked work.

    Each piece counts once, however many marks it carried: this is "the plain
    mean of marked work" (§3.3), so a 60-mark past paper does not drown out six
    short homeworks. Aggregating every question into one marks-over-total ratio
    was the alternative, and it answers a different question — how the student
    did across all marks — which is not what the surfaces claim.

    Pure: rows in, values out, no session (BE-4, CODE-3).
    """
    # submission_id -> [marks earned, marks available] across its marked questions
    totals: dict[int, list[int]] = {}
    for row in rows:
        # An unmarked question is excluded, never counted as a zero — a blank is
        # an absence of evidence, not evidence of failure (PROD-2, UX-19).
        if row.final_marks is None:
            continue
        bucket = totals.setdefault(row.submission_id, [0, 0])
        bucket[0] += row.final_marks
        bucket[1] += row.max_marks

    percentages = [got / mx * 100 for got, mx in totals.values() if mx > 0]
    if not percentages:
        return Averaging(score=None, marked_piece_count=0)
    return Averaging(
        score=round(sum(percentages) / len(percentages), 1),
        marked_piece_count=len(percentages),
    )


async def fetch_marked_rows(db: AsyncSession, student_id: int, subject_id: int) -> list[MarkRow]:
    """Every settled marked question this student has in this subject, from both
    kinds of submission.

    The two queries are what keeps `Submission`'s polymorphism honest (API-20):
    each joins through the identifier its own kind uses, so a past-paper
    submission — whose assignment_id is None — is excluded from the homework
    query by the join itself rather than by reading a column that may be null.
    A subject reaches homework through the group it was set to, and past papers
    directly.
    """
    homework = (
        await db.execute(
            select(
                QuestionMark.submission_id,
                QuestionMark.final_marks,
                AssignmentQuestion.max_marks,
            )
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .join(AssignmentQuestion, AssignmentQuestion.id == QuestionMark.question_id)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .join(Group, Group.id == Assignment.group_id)
            .where(
                Submission.student_id == student_id,
                Submission.status.in_(SETTLED),
                Group.subject_id == subject_id,
            )
        )
    ).all()

    past_papers = (
        await db.execute(
            select(
                QuestionMark.submission_id,
                QuestionMark.final_marks,
                PastPaperQuestion.max_marks,
            )
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .join(
                PastPaperQuestion,
                PastPaperQuestion.id == QuestionMark.past_paper_question_id,
            )
            .join(PastPaper, PastPaper.id == Submission.past_paper_id)
            .where(
                Submission.student_id == student_id,
                Submission.status.in_(SETTLED),
                PastPaper.subject_id == subject_id,
            )
        )
    ).all()

    return [MarkRow(*row) for row in (*homework, *past_papers)]


async def subject_averaging(db: AsyncSession, student_id: int, subject_id: int) -> Averaging:
    """The averaging value for one student in one subject. Mapping it to a grade
    is the caller's job, because which boundary list applies depends on which
    engine answered (see readiness_summary and readiness_summary_v2)."""
    return average_marked_work(await fetch_marked_rows(db, student_id, subject_id))
