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


async def test_an_enrolled_student_with_no_evidence_is_backfilled(client, subject, group, student):
    """Before 5.5 a no-evidence run stored a score the model made up. Those
    snapshots are only replaced by a fresh run, so the backfill has to reach
    exactly the pairs an evidence-based selection skips."""
    from seed.recompute_readiness import enrolled_pairs

    async with async_session() as session:
        assert await enrolled_pairs(session) == [(student["user"]["id"], subject["id"])]


async def test_main_queues_a_run_for_an_enrolled_student_with_no_evidence(
    client, subject, group, student
):
    await main(30)

    async with async_session() as session:
        payloads = [
            job.payload
            for job in (
                await session.scalars(select(Job).where(Job.type == "compute_readiness_v2"))
            ).all()
        ]
    assert payloads == [{"student_id": student["user"]["id"], "subject_id": subject["id"]}]


async def test_evidence_without_enrolment_is_not_backfilled(client, tutor, subject, group, student):
    """Enrolment, not evidence, is what selects a pair. Evidence left behind in
    a subject nobody is enrolled in belongs to a pair no screen reads, so a run
    for it would be an AI call whose snapshot is never shown."""
    from app.models import Evidence, EvidenceSource, Group, GroupMember
    from seed.recompute_readiness import enrolled_pairs

    async with async_session() as session:
        # The tutor is in no class, so this evidence is "stray".
        session.add(
            Evidence(
                student_id=tutor["user"]["id"],
                topic_id=subject["topic1"],
                source_type=EvidenceSource.quiz,
                score_pct=70.0,
                max_marks=0,
            )
        )
        # A second class in the same subject: one pair, not one per class.
        first = await session.get(Group, group["id"])
        second = Group(
            organization_id=first.organization_id,
            tutor_id=first.tutor_id,
            subject_id=first.subject_id,
            name="Chem Y10 B",
        )
        session.add(second)
        await session.flush()
        session.add(GroupMember(group_id=second.id, student_id=student["user"]["id"]))
        await session.commit()

        assert await enrolled_pairs(session) == [(student["user"]["id"], subject["id"])]
