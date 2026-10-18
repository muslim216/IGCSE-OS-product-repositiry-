"""A readiness run whose AI synthesis fails is said as a failure (OPS-10).

Before this, the failed snapshot was written and the job finished as done, so
the worker never retried a timeout, the queue showed nothing, and every screen
read the subject as "not enough data yet" — for a student with plenty of marked
work. These tests hold the three halves: the job fails after committing, the
retry is given only where it can help, and the summary says which state it is.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.db import async_session
from app.models import (
    AiSynthesisStatus,
    Group,
    GroupMember,
    Job,
    JobStatus,
    ReadinessSnapshot,
    Subject,
)
from app.services import readiness_v2_ai
from app.services.ai import AIOutputTruncatedError, AITimeoutError
from app.services.readiness_v2_ai import ReadinessSynthesis, compute_readiness_v2
from app.workers.jobs import enqueue, process_one_job
from tests.factories import subject_defaults
from tests.test_readiness_api import world  # noqa: F401 - shared fixture

JOB = "compute_readiness_v2"


async def _marked_work(client, tutor, world) -> None:  # noqa: F811
    """One scored mock, entered as a tutor would, so the run has evidence and
    reaches the model."""
    score = {"student_id": world["student_id"], "topic_id": world["topic1"]}
    resp = await client.post(
        "/api/v1/assessments",
        json={
            "subject_id": world["subject_id"],
            "title": "Mock",
            "type": "mock",
            "date": date.today().isoformat(),
            "scores": [score | {"marks": 10, "max_marks": 20}],
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text


async def _queue_run(world) -> None:  # noqa: F811
    async with async_session() as session:
        # Whatever the fixture's own actions queued is cleared, so the job
        # under test is the only one the worker can claim.
        for job in await session.scalars(select(Job)):
            await session.delete(job)
        await enqueue(
            session, JOB, {"student_id": world["student_id"], "subject_id": world["subject_id"]}
        )
        await session.commit()


async def _the_job() -> Job:
    async with async_session() as session:
        job = await session.scalar(select(Job).where(Job.type == JOB))
        assert job is not None
        return job


async def _snapshots(student_id: int) -> list[ReadinessSnapshot]:
    async with async_session() as session:
        return list(
            await session.scalars(
                select(ReadinessSnapshot)
                .where(ReadinessSnapshot.student_id == student_id)
                .order_by(ReadinessSnapshot.id)
            )
        )


def _raising(exc: Exception):
    async def fake(**_kwargs):
        raise exc

    return fake


# --- The job ---------------------------------------------------------------


async def test_a_timeout_fails_the_job_and_the_retry_produces_the_score(
    client, tutor, world, monkeypatch, fake_ai
):
    await _marked_work(client, tutor, world)
    await _queue_run(world)
    monkeypatch.setattr(
        "app.services.readiness_v2_ai.structured_complete",
        _raising(AITimeoutError("The AI did not answer in time")),
    )

    assert await asyncio.wait_for(process_one_job(), timeout=10) is True

    job = await _the_job()
    # Back in the queue for its one retry, not finished as done.
    assert job.status == JobStatus.pending
    assert job.attempts == 1
    assert job.run_after is not None
    assert job.error == "The AI did not answer in time"
    # The failed snapshot was committed before the raise, not rolled back.
    [failed] = await _snapshots(world["student_id"])
    assert failed.status == AiSynthesisStatus.failed

    monkeypatch.setattr(
        "app.services.readiness_v2_ai.structured_complete",
        fake_ai(ReadinessSynthesis(score=50.0, rationale="r", recommended_revision="-")),
    )
    async with async_session() as session:
        # Past the 60s backoff without waiting for it.
        await session.execute(update(Job).where(Job.id == job.id).values(run_after=None))
        await session.commit()
    assert await asyncio.wait_for(process_one_job(), timeout=10) is True

    assert (await _the_job()).status == JobStatus.done
    assert [s.status for s in await _snapshots(world["student_id"])] == [
        AiSynthesisStatus.failed,
        AiSynthesisStatus.ready,
    ]


@pytest.mark.usefixtures("no_ai_key")
async def test_a_missing_key_fails_the_job_at_once_without_a_retry(client, tutor, world):
    """No key in tests: a minute later the key is still missing, so the one
    retry would only spend a slot."""
    await _marked_work(client, tutor, world)
    await _queue_run(world)

    assert await asyncio.wait_for(process_one_job(), timeout=10) is True

    job = await _the_job()
    assert job.status == JobStatus.failed
    assert job.attempts == 1
    [failed] = await _snapshots(world["student_id"])
    assert failed.status == AiSynthesisStatus.failed


async def test_a_failure_is_logged_with_the_student_and_subject(
    client, tutor, world, monkeypatch, caplog
):
    await _marked_work(client, tutor, world)
    monkeypatch.setattr(
        "app.services.readiness_v2_ai.structured_complete",
        _raising(AITimeoutError("The AI did not answer in time")),
    )
    with caplog.at_level("WARNING", logger="readiness_v2_ai"):
        async with async_session() as session:
            with pytest.raises(AITimeoutError):
                await compute_readiness_v2(
                    session,
                    {"student_id": world["student_id"], "subject_id": world["subject_id"]},
                )
    [record] = [r for r in caplog.records if "readiness synthesis failed" in r.getMessage()]
    assert record.levelname == "WARNING"
    assert f"student {world['student_id']}" in record.getMessage()
    assert f"subject {world['subject_id']}" in record.getMessage()
    # The class name only: the message can carry provider detail.
    assert "did not answer" not in record.getMessage()


async def _second_subject(world) -> int:  # noqa: F811
    """Enrol the fixture's student in a second subject, for an all-subjects run."""
    async with async_session() as session:
        first = await session.get(Group, world["group"]["id"])
        subject = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4PH1",
            name="Physics",
            grade_scale="9-1",
        )
        session.add(subject)
        await session.flush()
        group = Group(
            organization_id=first.organization_id,
            tutor_id=first.tutor_id,
            subject_id=subject.id,
            name="Phys",
        )
        session.add(group)
        await session.flush()
        session.add(GroupMember(group_id=group.id, student_id=world["student_id"]))
        await session.commit()
        return subject.id


@pytest.mark.parametrize("timeout_on_first", [True, False])
async def test_one_subject_failing_keeps_the_others_and_prefers_a_retryable_failure(
    client, tutor, world, monkeypatch, timeout_on_first
):
    """An all-subjects run where one subject meets a cut-off answer (not worth
    retrying) and the other a timeout (worth it): the timeout is what the job
    raises, so the worker still gives the run its retry. Every snapshot the
    run wrote is kept."""
    physics = await _second_subject(world)
    real = readiness_v2_ai._synthesize_subject
    # Both ways round, so the test does not lean on the order the enrolment
    # query happens to return subjects in.
    cut_off = AIOutputTruncatedError("cut off")
    timeout = AITimeoutError("The AI did not answer in time")
    first, second = (timeout, cut_off) if timeout_on_first else (cut_off, timeout)
    outcomes = {world["subject_id"]: first, physics: second}

    async def synthesize(session, student, subject_id, now):
        # The real call writes a no-evidence ready snapshot for both subjects
        # (neither has marked work) — the rows this test checks are kept.
        await real(session, student, subject_id, now)
        return outcomes[subject_id]

    monkeypatch.setattr(readiness_v2_ai, "_synthesize_subject", synthesize)

    async with async_session() as session:
        with pytest.raises(AITimeoutError) as raised:
            await compute_readiness_v2(session, {"student_id": world["student_id"]})
    assert raised.value is timeout

    assert {s.subject_id for s in await _snapshots(world["student_id"])} == {
        world["subject_id"],
        physics,
    }


async def test_only_permanent_failures_raise_the_first_one(client, tutor, world, monkeypatch):
    physics = await _second_subject(world)
    first = AIOutputTruncatedError("cut off")
    outcomes = {world["subject_id"]: first, physics: AIOutputTruncatedError("also cut off")}

    async def synthesize(session, student, subject_id, now):
        return outcomes[subject_id]

    monkeypatch.setattr(readiness_v2_ai, "_synthesize_subject", synthesize)

    async with async_session() as session:
        with pytest.raises(AIOutputTruncatedError) as raised:
            await compute_readiness_v2(session, {"student_id": world["student_id"]})
    assert raised.value is first


# --- What the screens are told ---------------------------------------------


async def _snapshot_history(
    world,  # noqa: F811
    statuses: list[AiSynthesisStatus],
    step: timedelta = timedelta(minutes=1),
) -> None:
    """Snapshots in the given order, oldest first, `step` apart (zero for a
    tie, which the row id then breaks). A ready one carries a score so it is
    told apart from the no-snapshot shape."""
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    async with async_session() as session:
        for i, status in enumerate(statuses):
            ready = status == AiSynthesisStatus.ready
            session.add(
                ReadinessSnapshot(
                    evaluation_run_id=f"run-{i}",
                    student_id=world["student_id"],
                    subject_id=world["subject_id"],
                    status=status,
                    score=62.0 if ready else None,
                    predicted_grade="4" if ready else None,
                    weak_topics=[],
                    error=None if ready else "The AI did not answer in time",
                    created_at=start + step * i,
                )
            )
        await session.commit()


async def _my_subject(client, world) -> dict:  # noqa: F811
    resp = await client.get("/api/v1/readiness/me", headers=world["student_headers"])
    assert resp.status_code == 200, resp.text
    [subject] = [s for s in resp.json()["subjects"] if s["subject_id"] == world["subject_id"]]
    return subject


async def test_a_failure_with_no_score_before_it_is_couldnt_be_calculated(client, tutor, world):
    await _snapshot_history(world, [AiSynthesisStatus.failed])
    subject = await _my_subject(client, world)
    assert subject["calculation_failed"] is True
    # Still absent, never 0 (PROD-2).
    assert subject["score"] is None


async def test_a_failure_after_a_score_keeps_the_score_and_says_it_is_behind(client, tutor, world):
    await _snapshot_history(world, [AiSynthesisStatus.ready, AiSynthesisStatus.failed])
    subject = await _my_subject(client, world)
    assert subject["calculation_failed"] is True
    assert subject["score"] == 62.0


async def test_a_score_after_a_failure_clears_it(client, tutor, world):
    await _snapshot_history(world, [AiSynthesisStatus.failed, AiSynthesisStatus.ready])
    subject = await _my_subject(client, world)
    assert subject["calculation_failed"] is False
    assert subject["score"] == 62.0


async def test_a_subject_never_calculated_is_not_a_failure(client, tutor, world):
    subject = await _my_subject(client, world)
    assert subject["calculation_failed"] is False
    assert subject["score"] is None


async def test_a_created_at_tie_is_broken_by_id(client, tutor, world):
    """Two runs stamped in the same instant: the later row is the newer one,
    as every other reader of snapshots orders them."""
    await _snapshot_history(
        world, [AiSynthesisStatus.ready, AiSynthesisStatus.failed], step=timedelta(0)
    )
    subject = await _my_subject(client, world)
    assert subject["calculation_failed"] is True
    assert subject["score"] == 62.0
