"""Handing in again before marking starts queues no second marking (launch audit SA-07).

Each marking is a paid model call, and a student re-uploading a blurry page used
to queue one per hand-in for the same attempt."""

from sqlalchemy import select

from app.db import async_session
from app.models import Job, JobStatus, SubmissionFile
from app.workers.jobs import process_one_job
from tests.conftest import PNG_BYTES


async def _hand_in(client, student, aid: int, name: str) -> None:
    resp = await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", (name, PNG_BYTES + name.encode(), "image/png"))],
        headers=student["headers"],
    )
    assert resp.status_code == 201, resp.text


async def _marking_jobs() -> list[Job]:
    async with async_session() as session:
        return list((await session.scalars(select(Job).where(Job.type == "mark_submission"))).all())


async def test_three_hand_ins_before_marking_mark_once_with_the_last_pages(
    client, student, published_assignment, monkeypatch
):
    marked: list[list[str]] = []

    async def counting(session, submission):
        files = (
            await session.scalars(
                select(SubmissionFile.name).where(SubmissionFile.submission_id == submission.id)
            )
        ).all()
        marked.append(list(files))

    monkeypatch.setattr("app.services.marking._run_marking", counting)
    aid = published_assignment["id"]
    for name in ("first.png", "second.png", "last.png"):
        await _hand_in(client, student, aid, name)

    jobs = await _marking_jobs()
    assert len(jobs) == 1
    assert jobs[0].status == JobStatus.pending

    while await process_one_job():
        pass
    assert marked == [["last.png"]]


async def test_a_hand_in_while_marking_runs_is_marked_again_afterwards(
    client, student, published_assignment
):
    aid = published_assignment["id"]
    await _hand_in(client, student, aid, "first.png")
    (job,) = await _marking_jobs()
    # The worker has claimed it: that run read the first pages, so the new ones
    # need a run of their own.
    async with async_session() as session:
        claimed = await session.get(Job, job.id)
        claimed.status = JobStatus.running
        await session.commit()

    await _hand_in(client, student, aid, "second.png")
    jobs = await _marking_jobs()
    assert sorted(j.status for j in jobs) == sorted([JobStatus.running, JobStatus.pending])
