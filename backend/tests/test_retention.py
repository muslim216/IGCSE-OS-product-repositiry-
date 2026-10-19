"""What stops being kept (`services/retention.py`), against the owner's periods:
finished jobs and orphaned files 30 days, readiness working rows 90 days with the
latest run always kept, and nothing a row still points at."""

import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import async_session
from app.models import (
    AiSynthesisStatus,
    AttemptRedo,
    Classified,
    FactorConfidence,
    FactorEvaluation,
    Job,
    JobStatus,
    ReadinessFactor,
    ReadinessSnapshot,
)
from app.services import retention
from app.workers.jobs import process_one_job

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _own_upload_dir(tmp_path, monkeypatch):
    """The suite shares one upload folder, whose files outlive their rows from
    test to test; here every one of them would look orphaned."""
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))


def _ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


async def test_finished_jobs_go_after_30_days_and_nothing_unfinished_does():
    async with async_session() as session:
        session.add_all(
            [
                Job(type="x", payload={}, status=JobStatus.done, created_at=_ago(31)),
                Job(type="x", payload={}, status=JobStatus.failed, created_at=_ago(31)),
                Job(type="x", payload={}, status=JobStatus.done, created_at=_ago(29)),
                Job(type="x", payload={}, status=JobStatus.pending, created_at=_ago(60)),
                Job(type="x", payload={}, status=JobStatus.running, created_at=_ago(60)),
            ]
        )
        await session.commit()
        assert await retention.prune_finished_jobs(session, NOW) == 2
        left = (await session.scalars(select(Job.status))).all()
    assert sorted(left) == sorted([JobStatus.done, JobStatus.pending, JobStatus.running])


def _evaluation(run: str, student_id: int, subject_id: int, days: int) -> FactorEvaluation:
    return FactorEvaluation(
        evaluation_run_id=run,
        student_id=student_id,
        subject_id=subject_id,
        factor=ReadinessFactor.topic_mastery,
        confidence=FactorConfidence.low,
        detail={},
        created_at=_ago(days),
    )


def _snapshot(
    run: str,
    student_id: int,
    subject_id: int,
    days: int,
    status: AiSynthesisStatus = AiSynthesisStatus.ready,
) -> ReadinessSnapshot:
    return ReadinessSnapshot(
        evaluation_run_id=run,
        student_id=student_id,
        subject_id=subject_id,
        status=status,
        score=50.0 if status == AiSynthesisStatus.ready else None,
        created_at=_ago(days),
    )


async def test_readiness_working_rows_keep_90_days_and_always_the_latest_run(student, subject):
    sid, subj = student["user"]["id"], subject["id"]
    async with async_session() as session:
        # Old, superseded: goes. Recent: stays. And a pair whose newest run is
        # itself old keeps that run, since it is what its score stands on.
        session.add_all(
            [
                _snapshot("old", sid, subj, 120),
                _evaluation("old", sid, subj, 120),
                _snapshot("recent", sid, subj, 10),
                _evaluation("recent", sid, subj, 10),
            ]
        )
        await session.commit()
        assert await retention.prune_readiness_working_rows(session, NOW) == 1
        runs = (await session.scalars(select(FactorEvaluation.evaluation_run_id))).all()
        snapshots = await session.scalar(select(func.count(ReadinessSnapshot.id)))
    assert runs == ["recent"]
    assert snapshots == 2  # the score history is kept

    async with async_session() as session:
        await session.execute(
            FactorEvaluation.__table__.delete()  # start the second case clean
        )
        session.add_all([_snapshot("only", sid, subj, 5), _evaluation("only", sid, subj, 200)])
        await session.commit()
        assert await retention.prune_readiness_working_rows(session, NOW) == 0


async def test_the_score_on_screen_keeps_its_rows_when_newer_runs_failed(student, subject):
    """The pages show the latest *ready* snapshot. Newer failed runs (an AI
    outage, say) must not leave that score with its working rows deleted."""
    sid, subj = student["user"]["id"], subject["id"]
    async with async_session() as session:
        session.add_all(
            [
                _snapshot("shown", sid, subj, 120),
                _evaluation("shown", sid, subj, 120),
                _snapshot("failed", sid, subj, 100, AiSynthesisStatus.failed),
                _evaluation("failed", sid, subj, 100),
            ]
        )
        await session.commit()
        assert await retention.prune_readiness_working_rows(session, NOW) == 0


def _age(path: Path, days: int) -> None:
    when = _ago(days).timestamp()
    os.utime(path, (when, when))


def _stored(key: str, days: int) -> Path:
    path = Path(get_settings().upload_dir) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4")
    _age(path, days)
    return path


async def test_only_old_unreferenced_files_of_our_own_shape_are_deleted(classified):
    async with async_session() as session:
        referenced_key = await session.scalar(
            select(Classified.file_path).where(Classified.id == classified["id"])
        )
    referenced = Path(get_settings().upload_dir) / referenced_key
    _age(referenced, 400)
    orphan = _stored(f"org/1/{secrets.token_hex(16)}.pdf", 31)
    legacy_orphan = _stored(f"{secrets.token_hex(16)}.jpg", 31)
    recent_orphan = _stored(f"org/1/{secrets.token_hex(16)}.pdf", 29)
    not_ours = _stored("org/1/notes.pdf", 400)

    async with async_session() as session:
        assert await retention.prune_orphaned_files(session, NOW) == 2

    assert referenced.exists()  # a row still points at it: somebody's work
    assert not orphan.exists()
    assert not legacy_orphan.exists()
    assert recent_orphan.exists()
    assert not_ours.exists()


async def test_pages_kept_only_in_a_redo_record_are_not_orphans(student):
    """A redo moves the old attempt into `AttemptRedo.record` and deletes its
    file rows; the pages are kept so a dispute stays answerable."""
    kept = f"org/1/{secrets.token_hex(16)}.jpg"
    page = _stored(kept, 60)
    async with async_session() as session:
        session.add(
            AttemptRedo(
                organization_id=1,
                work_id=1,
                student_id=student["user"]["id"],
                allowed_by_id=1,
                previous_submission_id=1,
                record={"files": [{"id": 9, "path": kept, "position": 0}]},
            )
        )
        await session.commit()
        assert await retention.prune_orphaned_files(session, NOW) == 0
    assert page.exists()


def test_every_file_column_is_counted_as_somebodys_work():
    """A column that holds a storage key and is missing here would have its
    files deleted. This names the ones that exist today, so a new one is a
    decision rather than an accident."""
    found = {f"{c.table.name}.{c.name}" for c in retention.file_columns()}
    assert {
        "submission_files.path",
        "classifieds.file_path",
        "classifieds.mark_scheme_path",
        "past_papers.paper_path",
        "past_papers.mark_scheme_path",
    } <= found
    assert "notifications.link_path" not in found


async def test_the_sweep_runs_as_a_job_and_schedules_tomorrows():
    async with async_session() as session:
        await retention.ensure_retention_sweep_scheduled(session)
        await retention.ensure_retention_sweep_scheduled(session)  # idempotent
        await session.commit()
    assert await process_one_job() is True
    async with async_session() as session:
        sweeps = (await session.scalars(select(Job).where(Job.type == retention.SWEEP_JOB))).all()
    assert sorted(job.status for job in sweeps) == sorted([JobStatus.done, JobStatus.pending])
    pending = next(job for job in sweeps if job.status == JobStatus.pending)
    assert pending.run_after is not None


async def test_one_failing_step_does_not_stop_the_others(monkeypatch):
    """A step that fails every day must not leave the disk to fill: the rest
    still run, the job still fails, and tomorrow's run is still queued."""
    orphan = _stored(f"org/1/{secrets.token_hex(16)}.pdf", 31)

    async def broken(session, now):
        raise RuntimeError("statement timeout")

    monkeypatch.setattr(retention, "prune_finished_jobs", broken)
    async with async_session() as session:
        await retention.ensure_retention_sweep_scheduled(session)
        await session.commit()
    await process_one_job()
    assert not orphan.exists()  # the file step ran after the failure
    async with async_session() as session:
        sweeps = (await session.scalars(select(Job).where(Job.type == retention.SWEEP_JOB))).all()
    assert JobStatus.pending in {job.status for job in sweeps}
    assert any(job.error and "finished jobs" in job.error for job in sweeps)
