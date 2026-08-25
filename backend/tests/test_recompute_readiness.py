"""Task 0.2's backfill runner: spacing validation, and the two in-flight-job
gaps a review pass on it found (running-status jobs, wildcard subject_id=None
jobs) — see seed/recompute_readiness.py's already_pending() docstring."""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import Job, JobStatus
from app.workers.jobs import enqueue
from seed.recompute_readiness import already_pending, main


async def test_negative_or_zero_spacing_is_rejected(client):
    with pytest.raises(SystemExit):
        await main(0)
    with pytest.raises(SystemExit):
        await main(-5)


async def test_already_pending_excludes_a_running_job_not_just_pending(client):
    async with async_session() as session:
        await enqueue(session, "compute_readiness_v2", {"student_id": 1, "subject_id": 2})
        job = (await session.scalars(select(Job))).first()
        job.status = JobStatus.running
        await session.commit()

        pending = await already_pending(session, [(1, 2), (1, 3)])

    assert (1, 2) in pending
    assert (1, 3) not in pending


async def test_already_pending_wildcard_covers_every_subject_for_that_student(client):
    async with async_session() as session:
        await enqueue(session, "compute_readiness_v2", {"student_id": 9, "subject_id": None})
        await session.commit()

        pending = await already_pending(session, [(9, 1), (9, 2), (8, 1)])

    assert (9, 1) in pending
    assert (9, 2) in pending
    assert (8, 1) not in pending
