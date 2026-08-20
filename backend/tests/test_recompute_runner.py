"""seed/recompute_readiness.py — the operator backfill that re-queues a
Readiness v2 synthesis for every student holding evidence (task 0.2, AV-29, E4)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.models import Evidence, EvidenceSource, Job, JobStatus, Subject, Topic
from seed.recompute_readiness import STAGGER_SECONDS, enqueue_all
from tests.test_readiness_api import world  # noqa: F401 - shared fixture

NOW = datetime.now(timezone.utc)


async def _add_evidence(student_id: int, topic_id: int) -> None:
    async with async_session() as session:
        session.add(
            Evidence(
                student_id=student_id,
                topic_id=topic_id,
                source_type=EvidenceSource.observation,
                score_pct=70.0,
                max_marks=0,
                occurred_at=NOW - timedelta(days=1),
            )
        )
        await session.commit()


async def _pending_v2_jobs() -> list[Job]:
    async with async_session() as session:
        return list(
            (
                await session.scalars(
                    select(Job)
                    .where(Job.type == "compute_readiness_v2", Job.status == JobStatus.pending)
                    .order_by(Job.id)
                )
            ).all()
        )


async def test_enqueues_one_run_per_student_subject_pair(client, tutor, world):
    # Two topics of the *same* subject: one pair, not two.
    await _add_evidence(world["student_id"], world["topic1"])
    await _add_evidence(world["student_id"], world["topic2"])

    async with async_session() as session:
        count = await enqueue_all(session)
        await session.commit()

    assert count == 1
    jobs = await _pending_v2_jobs()
    assert len(jobs) == 1
    assert jobs[0].payload == {
        "student_id": world["student_id"],
        "subject_id": world["subject_id"],
    }


async def test_runs_are_staggered_rather_than_fired_at_once(client, tutor, world):
    """Each synthesis is an AI call, so a backfill must not fire as one burst."""
    await _add_evidence(world["student_id"], world["topic1"])

    # A second subject for the same student gives a second pair to stagger.
    async with async_session() as session:
        other = Subject(
            exam_board="Edexcel IGCSE",
            code="4PH1",
            name="Physics",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "U", "min": 0}],
        )
        session.add(other)
        await session.flush()
        topic = Topic(subject_id=other.id, code="2.1", title="Forces", weight=1.0)
        session.add(topic)
        await session.commit()
        other_topic_id = topic.id
    await _add_evidence(world["student_id"], other_topic_id)

    async with async_session() as session:
        count = await enqueue_all(session)
        await session.commit()

    assert count == 2
    jobs = await _pending_v2_jobs()
    assert len(jobs) == 2
    # Compared against each other rather than against "now": both values come
    # from the same store, so this holds whatever the driver returns.
    # Each enqueue reads the clock afresh, so the gap is STAGGER_SECONDS plus
    # the microseconds spent between the two calls — not exactly equal to it.
    gap = (jobs[1].run_after - jobs[0].run_after).total_seconds()
    assert STAGGER_SECONDS <= gap < STAGGER_SECONDS + 5


async def test_a_student_with_no_evidence_is_not_queued(client, tutor, world):
    async with async_session() as session:
        count = await enqueue_all(session)
        await session.commit()

    assert count == 0
    assert await _pending_v2_jobs() == []


async def test_rerunning_does_not_duplicate_a_pending_run(client, tutor, world):
    """Safe to re-run if interrupted: the debounce is per (student, subject)."""
    await _add_evidence(world["student_id"], world["topic1"])

    async with async_session() as session:
        await enqueue_all(session)
        await session.commit()
    async with async_session() as session:
        await enqueue_all(session)
        await session.commit()

    assert len(await _pending_v2_jobs()) == 1
