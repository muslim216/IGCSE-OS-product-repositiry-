from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, utcnow


class WorkerHeartbeat(TimestampMixin, Base):
    """One row per running worker process, holding the liveness clocks the
    readiness endpoint reads (task 1.3, AV-82, E19).

    These four values lived in module globals in `workers/jobs.py` until the
    worker could run outside the API. That was correct while both were the same
    process and is unreadable once they are not: the API cannot see another
    process's memory, so `/health/ready` would report on a worker that is not
    the one doing the work.

    Deliberately **not** tenant-scoped, and so exempt from `PROD-3`/`DB-2`: a
    worker serves every organization, and an `organization_id` here would either
    be meaningless or imply an isolation that does not exist. Nothing in this
    table is tenant data — it is operational telemetry about a process.
    """

    __tablename__ = "worker_heartbeats"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Identifies the process, not the machine — a restarted process is a new
    #: worker with a fresh row, which is what makes a vanished worker visible as
    #: a row that stopped updating rather than one that silently changed meaning.
    worker_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Stamped before each claim attempt, so it answers "is the loop turning?"
    #: rather than "did a job finish?" — an idle queue and a dead loop otherwise
    #: look identical.
    last_loop_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Set while a job is in flight, NULL between jobs. Kept apart from
    #: last_loop_at because a worker part-way through a slow AI call is healthy
    #: and a worker whose loop has stopped is not; one clock cannot tell those
    #: apart without either paging on every slow marking run or staying silent
    #: through a dead loop.
    job_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ISO timestamps of recent supervisor restarts, pruned to the crash-loop
    #: window on write. A list rather than a second table: it is read only as
    #: "how many in the last N seconds", never joined or queried across workers,
    #: and it is bounded by that pruning.
    restarts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
