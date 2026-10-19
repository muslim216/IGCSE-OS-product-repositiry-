"""What Avora stops keeping, and when (`DB-05`, `OPS-17`, `C-9`).

The periods are the owner's (19 October 2026): "Keep finished background
records and replaced or orphaned uploaded files for 30 days, then clean them
out. Keep each student's latest readiness working data and 90 days of history.
Never delete a student's current work."

So, once a day:

- a job row that finished (done or failed) more than 30 days ago is deleted;
- a readiness working row (`FactorEvaluation`) more than 90 days old is
  deleted, unless it belongs to the run behind a student's latest snapshot for
  that subject. Snapshots themselves are kept: they are the score history, and
  each carries its own score;
- a stored file no row points at, last written more than 30 days ago, is
  deleted. Replacing a submission's pages leaves the old ones on disk
  (`attempts.open_attempt`); this is what finally removes them.

Every row that holds a storage key does so in a column named `path` or ending
in `_path` — that naming is what this module relies on to know a file is still
somebody's work, so a new key column must follow it. It errs towards keeping:
any such column counts, and only a key of the shape `storage.new_key` makes is
ever deleted. One bucket or upload folder must belong to one database; a file
another deployment's rows point at looks unreferenced from here.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, String, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import Base, FactorEvaluation, Job, JobStatus, ReadinessSnapshot
from app.services import storage
from app.workers.jobs import enqueue

log = logging.getLogger(__name__)

SWEEP_JOB = "sweep_retention"
SWEEP_INTERVAL = timedelta(days=1)

FINISHED_JOB_DAYS = 30
ORPHAN_FILE_DAYS = 30
READINESS_HISTORY_DAYS = 90

#: Rows per delete, committed one batch at a time so no statement nears the
#: 60 s ceiling (`db.STATEMENT_TIMEOUT_MS`) and no lock is held for long. A run
#: stops after `MAX_BATCHES`; the next day's carries on, so a first run against
#: months of backlog stays inside the job's time limit.
BATCH_SIZE = 2_000
MAX_BATCHES = 50
MAX_FILE_DELETES = 5_000

#: Ends in `_path` but holds a page route, not a storage key.
NOT_FILE_COLUMNS = {"notifications.link_path"}

#: The keys `storage.new_key` makes, and the bare `{random}.ext` keys rows
#: written before task 1.2 hold. Anything else in the folder is not ours to
#: delete.
_EXTENSIONS = "|".join(re.escape(ext) for ext in sorted(set(storage.ALLOWED_MIMES.values())))
_SERVER_KEY = re.compile(rf"(?:org/\d+/)?[0-9a-f]{{32}}(?:{_EXTENSIONS})")


async def _delete_in_batches(session: AsyncSession, model: type, *conditions: object) -> int:
    deleted = 0
    for _ in range(MAX_BATCHES):
        ids = (await session.scalars(select(model.id).where(*conditions).limit(BATCH_SIZE))).all()
        if not ids:
            break
        await session.execute(delete(model).where(model.id.in_(ids)))
        await session.commit()
        deleted += len(ids)
    return deleted


async def prune_finished_jobs(session: AsyncSession, now: datetime) -> int:
    return await _delete_in_batches(
        session,
        Job,
        Job.status.in_((JobStatus.done, JobStatus.failed)),
        Job.created_at < now - timedelta(days=FINISHED_JOB_DAYS),
    )


async def prune_readiness_working_rows(session: AsyncSession, now: datetime) -> int:
    ranked = select(
        ReadinessSnapshot.evaluation_run_id,
        func.row_number()
        .over(
            partition_by=(ReadinessSnapshot.student_id, ReadinessSnapshot.subject_id),
            # The order the readiness summary reads "latest" by.
            order_by=(ReadinessSnapshot.created_at.desc(), ReadinessSnapshot.id.desc()),
        )
        .label("rank"),
    ).subquery()
    latest_runs = select(ranked.c.evaluation_run_id).where(ranked.c.rank == 1)
    return await _delete_in_batches(
        session,
        FactorEvaluation,
        FactorEvaluation.created_at < now - timedelta(days=READINESS_HISTORY_DAYS),
        FactorEvaluation.evaluation_run_id.not_in(latest_runs),
    )


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


async def _referenced_keys(session: AsyncSession) -> set[str]:
    keys: set[str] = set()
    for column in file_columns():
        keys.update(
            (await session.scalars(select(column).where(column.is_not(None)).distinct())).all()
        )
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
        await backend.delete(key)
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


async def sweep_retention(session: AsyncSession, payload: dict) -> None:
    """Job handler. Payload is `{}`; safe to re-run, since each step deletes only
    what is past its period and a second pass finds nothing more (`BE-6`)."""
    await _commit_successor_sweep()
    now = datetime.now(timezone.utc)
    jobs = await prune_finished_jobs(session, now)
    readiness = await prune_readiness_working_rows(session, now)
    files = await prune_orphaned_files(session, now)
    log.info(
        "retention: deleted %s finished jobs, %s readiness working rows, %s orphaned files",
        jobs,
        readiness,
        files,
    )
