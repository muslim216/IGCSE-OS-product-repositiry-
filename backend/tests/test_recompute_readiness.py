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


async def test_an_observation_only_pair_is_not_backfilled(client, tutor):
    """PROD-15: historical observation evidence does not make a (student,
    subject) pair readiness-bearing, so the backfill queues no run for it."""
    from app.models import Evidence, EvidenceSource, Subject, Topic
    from seed.recompute_readiness import pairs_with_evidence
    from tests.factories import subject_defaults

    async with async_session() as session:
        subject = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="X1",
            name="X",
            grade_scale="9-1",
        )
        session.add(subject)
        await session.flush()
        topic = Topic(subject_id=subject.id, code="1", title="t", weight=1.0)
        session.add(topic)
        await session.flush()
        session.add(
            Evidence(
                student_id=tutor["user"]["id"],
                topic_id=topic.id,
                source_type=EvidenceSource.observation,
                score_pct=80.0,
                max_marks=0,
            )
        )
        await session.commit()
        assert await pairs_with_evidence(session) == []

        # Positive control: readiness-bearing evidence on the same topic makes the
        # pair appear, so the empty list above is the filter, not a broken query.
        session.add(
            Evidence(
                student_id=tutor["user"]["id"],
                topic_id=topic.id,
                source_type=EvidenceSource.quiz,
                score_pct=70.0,
                max_marks=0,
            )
        )
        await session.commit()
        assert await pairs_with_evidence(session) == [(tutor["user"]["id"], subject.id)]
