"""Opening a student's attempt at a piece of work.

One function, because this logic existed three times — once in each of the
homework, past-paper and mock routers — and the copies had already drifted
twice. Homework reset `submitted_at` when a student replaced an attempt;
neither past papers nor mocks did, so a re-logged paper sat in the tutor's
review queue ordered by the attempt it had just replaced. The mock copy was
written from the homework one and lost the same line again.

That is the cost of a copied block: each divergence is invisible until someone
compares the three side by side. `API-20`'s discriminator already names which
foreign key each kind uses, so there is nothing kind-specific left here.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import SETTLED_STATUSES, AssessableWork, Submission, SubmissionStatus
from app.services.submission_kind import SubmissionKind


async def open_attempt(
    session: AsyncSession, kind: SubmissionKind, parent_id: int, student_id: int
) -> tuple[Submission, bool]:
    """Open a student's attempt, or re-open the one they already have.

    Returns `(submission, already_settled)`. The caller raises its own `409`
    when settled rather than this doing it, because the wording a student sees
    differs per kind — "already been marked and finalized" for homework reads
    wrong for a past paper they logged themselves.

    A replacement is the whole answer again, never a merge: the previous pages
    and every AI draft against them are deleted, which is what keeps
    `mark_submission` idempotent on a re-run (`BE-6`).
    """
    # The parent is loaded first because its `work_id` is what identifies the
    # attempt — a submission says which piece of work it answers and nothing
    # else (D6).
    parent = await session.get(kind.parent_model, parent_id)
    if parent is None:
        raise ValueError(f"no {kind.name} with id {parent_id}")

    submission = await session.scalar(
        select(Submission)
        .where(
            Submission.work_id == parent.work_id,
            Submission.student_id == student_id,
        )
        .options(selectinload(Submission.files), selectinload(Submission.marks))
    )
    if submission is not None and submission.status in SETTLED_STATUSES:
        return submission, True

    if submission is None:
        # The parent row is attached, not just its id. `Submission.work` is
        # eagerly loaded, but eager loading only fills a row read back from the
        # database — a submission built here and handed straight to the caller
        # would have nothing there, and the first reader to ask what kind of
        # work it is would raise `MissingGreenlet` instead of answering.
        work = await session.get(AssessableWork, parent.work_id)
        submission = Submission(student_id=student_id, work=work)
        session.add(submission)
        await session.flush()
        return submission, False

    for file in list(submission.files):
        await session.delete(file)
    for mark in list(submission.marks):
        await session.delete(mark)
    submission.status = SubmissionStatus.submitted
    submission.ai_error = None
    # The review queue orders by this. Keeping the first attempt's timestamp
    # sorts a resubmission as though it never happened.
    submission.submitted_at = datetime.now(timezone.utc)
    await session.flush()
    return submission, False
