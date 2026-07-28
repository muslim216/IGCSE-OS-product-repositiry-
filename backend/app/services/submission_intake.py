"""Opening a submission for a fresh set of files.

Shared by the student upload endpoint and the Google Classroom importer, so
"what a resubmission does" has one implementation rather than two that drift.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Submission, SubmissionStatus


class SubmissionFinalized(Exception):
    """The tutor has already signed off these marks; don't clobber them."""


async def open_submission_for_files(
    session: AsyncSession,
    assignment_id: int,
    student_id: int,
    submitted_at: datetime | None = None,
) -> Submission:
    """Get or create the student's submission, cleared and ready for new files.

    A resubmission before finalize replaces the files and drops the old marks so
    marking starts clean. After finalize it raises instead.
    """
    submission = await session.scalar(
        select(Submission)
        .where(Submission.assignment_id == assignment_id, Submission.student_id == student_id)
        .options(selectinload(Submission.files), selectinload(Submission.marks))
    )
    if submission is not None and submission.status == SubmissionStatus.finalized:
        raise SubmissionFinalized("This homework has already been marked and finalized")

    if submission is None:
        submission = Submission(assignment_id=assignment_id, student_id=student_id)
        if submitted_at is not None:
            submission.submitted_at = submitted_at
        session.add(submission)
        await session.flush()
        return submission

    for f in submission.files:
        await session.delete(f)
    for m in submission.marks:
        await session.delete(m)
    submission.status = SubmissionStatus.submitted
    submission.ai_error = None
    submission.submitted_at = submitted_at or datetime.now(timezone.utc)
    await session.flush()
    return submission
