"""Task 6: queuing tag_mistakes from where marks settle, plus the manual
backfill. Put in a separate file (not tests/test_mistake_tagging.py, per the
plan) because another agent holds that file for task 4's work concurrently."""

from sqlalchemy import select

from app.db import async_session
from app.models import Job, JobStatus, Submission
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


async def test_finalizing_an_already_auto_finalized_submission_does_not_queue_a_second_run(
    client,
    tutor,
    student,
    assignment_all_scheme,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """`finalize_submission` rejects only `finalized`, not `auto_finalized`, so
    a tutor pressing finalize on a submission the AI already settled reaches
    `record_marks_as_evidence` a second time with nothing changed for the
    second run to find. The handler is safe to re-run (`BE-6`) but not free to
    — each run is a paid AI call (`AI-17`), so the enqueue is deduped against
    pending jobs the way the class narrative beside it already is."""
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    await _submit(client, assignment_all_scheme, student)

    async with async_session() as session:
        submission_id = await session.scalar(select(Submission.id))

    second = await client.post(
        f"/api/v1/submissions/{submission_id}/finalize", headers=tutor["headers"]
    )
    assert second.status_code == 200

    async with async_session() as session:
        rows = (await session.execute(select(Job.type, Job.payload))).all()
    tag_jobs = [payload for job_type, payload in rows if job_type == "tag_mistakes"]
    assert len(tag_jobs) == 1
    assert tag_jobs[0]["submission_id"] == submission_id


async def test_a_tagging_job_already_in_flight_is_not_queued_a_second_time(
    client,
    tutor,
    student,
    assignment_all_scheme,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """`pending` is not the whole of "already queued". A claimed job commits
    `running` before its handler is invoked (`workers/jobs.py`), so for the
    whole length of the AI call it is in flight and invisible to a
    `pending`-only check — and that is precisely the window a tutor pressing
    finalize lands in. `seed/backfill_mistakes.py` checks both statuses; this
    path has to agree with it, or the two halves of the same task disagree
    about what "already queued" means and the gap is a second paid call
    (`AI-17`)."""
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    await _submit(client, assignment_all_scheme, student)

    async with async_session() as session:
        submission_id = await session.scalar(select(Submission.id))
        job = await session.scalar(select(Job).where(Job.type == "tag_mistakes"))
        job.status = JobStatus.running  # claimed, mid-AI-call
        await session.commit()

    second = await client.post(
        f"/api/v1/submissions/{submission_id}/finalize", headers=tutor["headers"]
    )
    assert second.status_code == 200

    async with async_session() as session:
        rows = (await session.execute(select(Job.type))).all()
    assert [t for (t,) in rows if t == "tag_mistakes"] == ["tag_mistakes"]
