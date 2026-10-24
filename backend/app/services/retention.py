"""What Avora stops keeping, and when (`DB-05`, `OPS-17`, `C-9`).

The periods are the owner's (19 October 2026): "Keep finished background
records and replaced or orphaned uploaded files for 30 days, then clean them
out. Keep each student's latest readiness working data and 90 days of history.
Never delete a student's current work."

So, once a day:

- a job row that finished (done or failed) more than 30 days ago is deleted;
- a readiness working row (`FactorEvaluation`) more than 90 days old is
  deleted, unless it belongs to the run behind a student's latest snapshot for
  that subject, or behind their latest *ready* one — the score the pages show
  when newer runs failed (`readiness_summary_v2.latest_ready_snapshot`).
  Snapshots themselves are kept: they are the score history, and each carries
  its own score;
- a stored file no row points at, last written more than 30 days ago, is
  deleted. Replacing a submission's pages leaves the old ones on disk
  (`attempts.open_attempt`); this is what finally removes them.

Every row that holds a storage key does so in a column named `path` or ending
in `_path` — that naming is what this module relies on to know a file is still
somebody's work, so a new key column must follow it. The one exception is the
redo record (`AttemptRedo.record`), which keeps the replaced attempt's pages in
JSON so a dispute stays answerable; its keys are read out of it. It errs towards keeping:
any such column counts, and only a key of the shape `storage.new_key` makes is
ever deleted. One bucket or upload folder must belong to one database; a file
another deployment's rows point at looks unreferenced from here.
"""

import logging
import re
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, String, and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import (
    AiSynthesisStatus,
    AttemptRedo,
    Base,
    FactorEvaluation,
    Job,
    JobStatus,
    ReadinessSnapshot,
)
from app.services import storage
from app.services.data_export import expire_data_exports
from app.workers.jobs import enqueue

log = logging.getLogger(__name__)

SWEEP_JOB = "sweep_retention"
SWEEP_INTERVAL = timedelta(days=1)

FINISHED_JOB_DAYS = 30
ORPHAN_FILE_DAYS = 30
READINESS_HISTORY_DAYS = 90

#: Rows per delete, committed one batch at a time so no statement nears the
#: 60 s ceiling (`db.STATEMENT_TIMEOUT_MS`) and no lock is held for long. Each
#: table's step stops after `STEP_SECONDS`; the next day's carries on, so a
#: first run against months of backlog stays well inside the job's time limit
#: (`workers/jobs.py`, 900 s).
BATCH_SIZE = 2_000
STEP_SECONDS = 240
MAX_FILE_DELETES = 5_000

#: Ends in `_path` but holds a page route, not a storage key.
NOT_FILE_COLUMNS = {"notifications.link_path"}

#: The keys `storage.new_key` makes, and the bare `{random}.ext` keys rows
#: written before task 1.2 hold. Anything else in the folder is not ours to
#: delete.
_EXTENSIONS = "|".join(re.escape(ext) for ext in sorted(set(storage.ALLOWED_MIMES.values())))
_SERVER_KEY = re.compile(rf"(?:org/\d+/)?[0-9a-f]{{32}}(?:{_EXTENSIONS})")


async def prune_finished_jobs(session: AsyncSession, now: datetime) -> int:
    cutoff = now - timedelta(days=FINISHED_JOB_DAYS)
    deadline = time.monotonic() + STEP_SECONDS
    deleted = 0
    while time.monotonic() < deadline:
        ids = (
            await session.scalars(
                select(Job.id)
                .where(
                    Job.status.in_((JobStatus.done, JobStatus.failed)),
                    Job.created_at < cutoff,
                )
                .limit(BATCH_SIZE)
            )
        ).all()
        if not ids:
            break
        await session.execute(delete(Job).where(Job.id.in_(ids)))
        await session.commit()
        deleted += len(ids)
    return deleted


async def _protected_runs(session: AsyncSession) -> set[str]:
    """The run behind each (student, subject)'s latest snapshot, and behind its
    latest ready one. Read once per sweep."""
    protected: set[str] = set()
    for only_ready in (False, True):
        ranked = select(
            ReadinessSnapshot.evaluation_run_id,
            func.row_number()
            .over(
                partition_by=(ReadinessSnapshot.student_id, ReadinessSnapshot.subject_id),
                # The order the readiness summary reads "latest" by.
                order_by=(ReadinessSnapshot.created_at.desc(), ReadinessSnapshot.id.desc()),
            )
            .label("rank"),
        )
        if only_ready:
            ranked = ranked.where(ReadinessSnapshot.status == AiSynthesisStatus.ready)
        sub = ranked.subquery()
        protected.update(
            (await session.scalars(select(sub.c.evaluation_run_id).where(sub.c.rank == 1))).all()
        )
    return protected


async def prune_readiness_working_rows(session: AsyncSession, now: datetime) -> int:
    cutoff = now - timedelta(days=READINESS_HISTORY_DAYS)
    protected = await _protected_runs(session)
    deadline = time.monotonic() + STEP_SECONDS
    deleted = 0
    # Walked in index order (`ix_factor_evaluations_created_at_id`) from where
    # the last batch stopped, so a protected old run is stepped over once
    # rather than re-read by every batch.
    after: tuple[datetime, int] | None = None
    while time.monotonic() < deadline:
        query = (
            select(
                FactorEvaluation.id, FactorEvaluation.created_at, FactorEvaluation.evaluation_run_id
            )
            .where(FactorEvaluation.created_at < cutoff)
            .order_by(FactorEvaluation.created_at, FactorEvaluation.id)
            .limit(BATCH_SIZE)
        )
        if after is not None:
            at, last_id = after
            query = query.where(
                or_(
                    FactorEvaluation.created_at > at,
                    and_(FactorEvaluation.created_at == at, FactorEvaluation.id > last_id),
                )
            )
        rows = (await session.execute(query)).all()
        if not rows:
            break
        after = (rows[-1].created_at, rows[-1].id)
        doomed = [row.id for row in rows if row.evaluation_run_id not in protected]
        if doomed:
            await session.execute(delete(FactorEvaluation).where(FactorEvaluation.id.in_(doomed)))
            await session.commit()
            deleted += len(doomed)
    return deleted


def file_columns() -> list[Column]:
    """Every column that can hold a storage key (see the module docstring)."""
    return [
        column
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, String)
        and (column.name == "path" or column.name.endswith("_path"))
        and f"{table.name}.{column.name}" not in NOT_FILE_COLUMNS
    ]


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


async def _referenced_keys(session: AsyncSession) -> set[str]:
    keys: set[str] = set()
    for column in file_columns():
        keys.update(
            (await session.scalars(select(column).where(column.is_not(None)).distinct())).all()
        )
    # Every string of key shape anywhere in a redo record counts, so a change
    # to the record's layout can only keep more.
    for record in (await session.scalars(select(AttemptRedo.record))).all():
        keys.update(text for text in _strings(record) if _SERVER_KEY.fullmatch(text))
    return keys


async def prune_orphaned_files(session: AsyncSession, now: datetime) -> int:
    backend = storage.get_storage()
    cutoff = now - timedelta(days=ORPHAN_FILE_DAYS)
    # Listed before the rows are read: a row deleted in between keeps its file
    # until tomorrow, never the other way round. The age gate covers a file
    # whose row is still being written.
    stale = [
        key
        for key, written in await backend.list_objects()
        if written < cutoff and _SERVER_KEY.fullmatch(key)
    ]
    if not stale:
        return 0
    referenced = await _referenced_keys(session)
    deleted = 0
    for key in stale:
        if key in referenced:
            continue
        # One stuck file must not hold up the rest, every day.
        try:
            await backend.delete(key)
        except Exception:  # noqa: BLE001
            log.warning("retention: could not delete orphaned file %s", key, exc_info=True)
            continue
        deleted += 1
        if deleted >= MAX_FILE_DELETES:
            break
    return deleted


async def _pending_sweep_exists(session: AsyncSession) -> bool:
    return (
        await session.scalar(
            select(func.count(Job.id)).where(Job.type == SWEEP_JOB, Job.status == JobStatus.pending)
        )
        or 0
    ) > 0


async def ensure_retention_sweep_scheduled(session: AsyncSession) -> None:
    """Startup floor: if no sweep is pending, schedule one. Idempotent."""
    if await _pending_sweep_exists(session):
        return
    await enqueue(session, SWEEP_JOB, {})


async def _commit_successor_sweep() -> None:
    """Tomorrow's run, committed on its own so a failure today cannot lose the
    schedule (the reasoning is narrative's `_commit_successor_sweep`)."""
    async with async_session() as session:
        if await _pending_sweep_exists(session):
            return
        await enqueue(session, SWEEP_JOB, {}, run_after=datetime.now(timezone.utc) + SWEEP_INTERVAL)
        await session.commit()


async def sweep_retention(session: AsyncSession, _payload: dict) -> None:
    """Job handler. Payload is `{}`; safe to re-run, since each step deletes only
    what is past its period and a second pass finds nothing more (`BE-6`).

    Each step runs whatever the others did: one failing every day must not
    leave the disk to fill. A failure still fails the job, after all of them, so
    it is counted where failed jobs are."""
    await _commit_successor_sweep()
    now = datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    failed: list[str] = []
    for name, step in (
        ("finished jobs", prune_finished_jobs),
        ("readiness working rows", prune_readiness_working_rows),
        ("orphaned files", prune_orphaned_files),
        # A child's data export is kept 7 days (P-3); its own expiry, not the
        # orphan rule, owns its file.
        ("expired data exports", expire_data_exports),
    ):
        try:
            counts[name] = await step(session, now)
        except Exception:  # noqa: BLE001
            # Logged, and re-raised below once every step ran.
            await session.rollback()
            log.exception("retention: deleting %s failed", name)
            failed.append(name)
    log.info(
        "retention: deleted %s", ", ".join(f"{n} {name}" for name, n in counts.items()) or "nothing"
    )
    if failed:
        raise RuntimeError(f"retention: {', '.join(failed)} failed; see the log")
