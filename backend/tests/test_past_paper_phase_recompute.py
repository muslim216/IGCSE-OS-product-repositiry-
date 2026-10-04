"""AV-31 follow-up (Phase 7) — recompute readiness when a class's past-paper
phase opens.

The gate in readiness_factors.past_paper_phase_started only opens by the
calendar, and readiness recomputes only when evidence arrives, so the day the
start date passes nothing would refresh. The sweep finds those pairs and queues
the ordinary debounced v2 run. Assertions are on the queued Job rows: no
recompute runs here, so no AI provider is reachable (QA-8).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import async_session
from app.models import (
    AiSynthesisStatus,
    Group,
    GroupMember,
    Job,
    JobStatus,
    PastPaperAttempt,
    Subject,
    TeachingPlan,
    TeachingPlanStatus,
)
from app.services.past_paper_phase import (
    SWEEP_JOB,
    ensure_past_paper_phase_sweep_scheduled,
    pairs_needing_phase_recompute,
    sweep_past_paper_phase,
)
from app.workers.jobs import enqueue, process_one_job
from tests.factories import (
    make_past_paper,
    other_org_subject,
    subject_defaults,
    write_v2_snapshot,
)
from tests.factories import org_id as default_org_id

TODAY = datetime.now(timezone.utc).date()


@pytest.fixture
async def world(client, tutor):
    async with async_session() as session:
        subject = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
        )
        session.add(subject)
        await session.commit()
        subject_id = subject.id
    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    student = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Sara", "username": "sara01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    async with async_session() as session:
        tutor_id = tutor["user"]["id"]
        organization_id = await default_org_id(session)
    return {
        "group_id": group["id"],
        "student_id": student["id"],
        "subject_id": subject_id,
        "tutor_id": tutor_id,
        "org_id": organization_id,
    }


async def _plan(world, *, start, status=TeachingPlanStatus.accepted, group_id=None, org_id=None):
    accepted = status == TeachingPlanStatus.accepted
    async with async_session() as session:
        session.add(
            TeachingPlan(
                organization_id=org_id or world["org_id"],
                group_id=group_id or world["group_id"],
                status=status,
                exam_date=TODAY + timedelta(days=400),
                lessons_per_week=2,
                lesson_minutes=60,
                past_paper_start_date=start,
                accepted_at=datetime.now(timezone.utc) if accepted else None,
                accepted_by_id=world["tutor_id"] if accepted else None,
            )
        )
        await session.commit()


async def _attempt(world, *, subject_id=None, org_id=None, marks=15):
    async with async_session() as session:
        paper = await make_past_paper(
            session,
            subject_id=subject_id or world["subject_id"],
            organization_id=org_id or world["org_id"],
        )
        session.add(
            PastPaperAttempt(
                past_paper_id=paper.id,
                student_id=world["student_id"],
                raw_marks=marks,
                max_marks=20,
                timed=True,
                attempted_at=TODAY - timedelta(days=3),
            )
        )
        await session.commit()


async def _snapshot(world, created_at):
    async with async_session() as session:
        await write_v2_snapshot(
            session,
            student_id=world["student_id"],
            subject_id=world["subject_id"],
            score=50.0,
            created_at=created_at,
        )
        await session.commit()


async def _pairs():
    async with async_session() as session:
        return await pairs_needing_phase_recompute(session, TODAY)


async def _compute_jobs():
    async with async_session() as session:
        return (await session.scalars(select(Job).where(Job.type == "compute_readiness_v2"))).all()


async def _pending_sweeps() -> int:
    async with async_session() as session:
        return await session.scalar(
            select(func.count(Job.id)).where(Job.type == SWEEP_JOB, Job.status == JobStatus.pending)
        )


async def test_start_date_today_selects_the_pair(world):
    await _plan(world, start=TODAY)
    await _attempt(world)
    assert await _pairs() == [(world["student_id"], world["subject_id"])]


async def test_start_date_in_the_future_selects_nothing(world):
    await _plan(world, start=TODAY + timedelta(days=1))
    await _attempt(world)
    assert await _pairs() == []


async def test_null_start_date_selects_nothing(world):
    await _plan(world, start=None)
    await _attempt(world)
    assert await _pairs() == []


async def test_draft_plan_selects_nothing(world):
    await _plan(world, start=TODAY - timedelta(days=2), status=TeachingPlanStatus.draft)
    await _attempt(world)
    assert await _pairs() == []


async def test_no_past_paper_evidence_selects_nothing(world):
    await _plan(world, start=TODAY)
    assert await _pairs() == []


async def test_unmarked_attempt_is_not_evidence(world):
    await _plan(world, start=TODAY)
    async with async_session() as session:
        paper = await make_past_paper(
            session, subject_id=world["subject_id"], organization_id=world["org_id"]
        )
        session.add(
            PastPaperAttempt(
                past_paper_id=paper.id,
                student_id=world["student_id"],
                raw_marks=None,
                max_marks=20,
                timed=True,
                attempted_at=TODAY,
            )
        )
        await session.commit()
    assert await _pairs() == []


async def test_run_computed_before_the_start_date_is_selected(world):
    await _plan(world, start=TODAY - timedelta(days=1))
    await _attempt(world)
    await _snapshot(world, datetime.now(timezone.utc) - timedelta(days=5))
    assert await _pairs() == [(world["student_id"], world["subject_id"])]


async def test_run_computed_after_the_start_date_is_not_selected(world):
    """Idempotence: once recomputed the pair drops out."""
    await _plan(world, start=TODAY - timedelta(days=1))
    await _attempt(world)
    await _snapshot(world, datetime.now(timezone.utc))
    assert await _pairs() == []


async def test_failed_run_after_the_start_date_is_still_due(world, caplog):
    """An AI outage writes a failed snapshot; it must not count as fresh."""
    await _plan(world, start=TODAY - timedelta(days=1))
    await _attempt(world)
    async with async_session() as session:
        await write_v2_snapshot(
            session,
            student_id=world["student_id"],
            subject_id=world["subject_id"],
            score=None,
            created_at=datetime.now(timezone.utc),
            status=AiSynthesisStatus.failed,
        )
        await session.commit()
    with caplog.at_level("WARNING", logger="past_paper_phase"):
        assert await _pairs() == [(world["student_id"], world["subject_id"])]
    assert any("failed run" in r.message for r in caplog.records)


async def test_pending_wildcard_job_covers_the_pair(world):
    await _plan(world, start=TODAY)
    await _attempt(world)
    async with async_session() as session:
        await enqueue(
            session, "compute_readiness_v2", {"student_id": world["student_id"], "subject_id": None}
        )
        await session.commit()
    async with async_session() as session:
        await sweep_past_paper_phase(session, {})
        await session.commit()
    assert len(await _compute_jobs()) == 1


async def test_running_job_for_the_pair_is_not_requeued(world):
    await _plan(world, start=TODAY)
    await _attempt(world)
    async with async_session() as session:
        job = await enqueue(
            session,
            "compute_readiness_v2",
            {"student_id": world["student_id"], "subject_id": world["subject_id"]},
        )
        job.status = JobStatus.running
        await session.commit()
    async with async_session() as session:
        await sweep_past_paper_phase(session, {})
        await session.commit()
    assert len(await _compute_jobs()) == 1


async def test_evidence_in_another_organizations_subject_is_not_mixed_in(world):
    await _plan(world, start=TODAY)
    async with async_session() as session:
        rival = await other_org_subject(session, code="9RIV")
        await session.commit()
        rival_subject_id, rival_org = rival.id, rival.organization_id
    await _attempt(world, subject_id=rival_subject_id, org_id=rival_org)
    assert await _pairs() == []


async def test_a_plan_carrying_another_organizations_id_is_not_trusted(world):
    async with async_session() as session:
        rival = await other_org_subject(session, code="9RIV")
        await session.commit()
        rival_org = rival.organization_id
    await _plan(world, start=TODAY, org_id=rival_org)
    await _attempt(world)
    assert await _pairs() == []


async def test_two_classes_in_one_subject_give_one_pair(world):
    await _plan(world, start=TODAY)
    await _attempt(world)
    async with async_session() as session:
        second = Group(
            organization_id=world["org_id"],
            tutor_id=world["tutor_id"],
            subject_id=world["subject_id"],
            name="Chem 2",
        )
        session.add(second)
        await session.flush()
        session.add(GroupMember(group_id=second.id, student_id=world["student_id"]))
        await session.commit()
        second_id = second.id
    await _plan(world, start=TODAY, group_id=second_id)
    assert await _pairs() == [(world["student_id"], world["subject_id"])]


async def test_sweep_enqueues_the_pair_once_even_when_run_twice(world):
    await _plan(world, start=TODAY)
    await _attempt(world)
    for _ in range(2):
        async with async_session() as session:
            await sweep_past_paper_phase(session, {})
            await session.commit()
    jobs = await _compute_jobs()
    assert len(jobs) == 1
    assert jobs[0].payload == {
        "student_id": world["student_id"],
        "subject_id": world["subject_id"],
    }


async def test_kill_switch_off_enqueues_no_compute_jobs_but_still_rearms(world, monkeypatch):
    await _plan(world, start=TODAY)
    await _attempt(world)
    monkeypatch.setattr(get_settings(), "readiness_v2_shadow_enabled", False)
    async with async_session() as session:
        await sweep_past_paper_phase(session, {})
        await session.commit()
    assert await _compute_jobs() == []
    assert await _pending_sweeps() == 1


async def test_sweep_rearms_itself_with_future_run_after(world):
    async with async_session() as session:
        await sweep_past_paper_phase(session, {})
        await session.commit()
    async with async_session() as session:
        sweep = await session.scalar(
            select(Job).where(Job.type == SWEEP_JOB, Job.status == JobStatus.pending)
        )
    assert sweep is not None
    run_after = sweep.run_after
    if run_after.tzinfo is None:
        run_after = run_after.replace(tzinfo=timezone.utc)
    assert run_after > datetime.now(timezone.utc)


async def test_a_failing_sweep_still_leaves_the_next_one_scheduled(world, monkeypatch):
    async def explode(*args, **kwargs):
        raise RuntimeError("sweep body failed")

    monkeypatch.setattr("app.services.past_paper_phase.pairs_needing_phase_recompute", explode)
    async with async_session() as session:
        with pytest.raises(RuntimeError):
            await sweep_past_paper_phase(session, {})
    assert await _pending_sweeps() == 1, "a failing sweep must not take the schedule with it"


async def test_ensure_scheduled_is_idempotent(world):
    for _ in range(2):
        async with async_session() as session:
            await ensure_past_paper_phase_sweep_scheduled(session)
            await session.commit()
    async with async_session() as session:
        count = await session.scalar(select(func.count(Job.id)).where(Job.type == SWEEP_JOB))
    assert count == 1


async def test_handler_is_registered_and_runs_through_the_worker(world):
    """Through process_one_job (QA-6): the registered handler queues the compute
    job and the next sweep. The compute job is delayed, so no AI is called."""
    await _plan(world, start=TODAY)
    await _attempt(world)
    async with async_session() as session:
        await ensure_past_paper_phase_sweep_scheduled(session)
        await session.commit()
    assert await process_one_job() is True
    assert len(await _compute_jobs()) == 1
    assert await _pending_sweeps() == 1


def test_interval_setting_is_at_least_one_hour():
    assert get_settings().past_paper_phase_sweep_interval_hours >= 1
