"""Task 6: queuing tag_mistakes from where marks settle, plus the manual
backfill. Put in a separate file (not tests/test_mistake_tagging.py, per the
plan) because another agent holds that file for task 4's work concurrently."""

from sqlalchemy import select

from app.db import async_session
from app.models import Job, Submission
from tests.test_auto_marking import _confident_result, _submit, assignment_all_scheme  # noqa: F401


async def test_settling_a_submissions_marks_queues_the_tagging_job(
    client,
    tutor,
    student,
    assignment_all_scheme,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """Queued from where evidence is built, not from a router: marks settling
    is the event that makes tagging possible, and it happens on two paths —
    auto-finalize and the tutor's own finalize endpoint. `record_marks_as_
    evidence` is the one place both already meet."""
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    await _submit(client, assignment_all_scheme, student)

    async with async_session() as session:
        submission_id = await session.scalar(select(Submission.id))
        rows = (await session.execute(select(Job.type, Job.payload))).all()
    tag_jobs = [payload for job_type, payload in rows if job_type == "tag_mistakes"]
    assert len(tag_jobs) == 1
    # The id, not just the key. A payload naming the wrong submission — or
    # None — satisfies `"submission_id" in payload` and queues a job that
    # tags somebody else's work, or no work at all, with nothing failing.
    assert tag_jobs[0]["submission_id"] == submission_id
