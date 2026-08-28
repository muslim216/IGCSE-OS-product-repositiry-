# git test
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.api import (
    ai_usage,
    analytics,
    assessments,
    assignments,
    auth,
    classifieds,
    grade_boundaries,
    groups,
    lessons,
    me,
    narrative,
    past_papers,
    preferences,
    readiness,
    readiness_v2,
    readiness_weights,
    reports,
    resources,
    students,
    subjects,
    submissions,
    syllabus_uploads,
    today,
)
from app.config import get_settings
from app.db import async_session
from app.models import Job, JobStatus
from app.services.narrative import ensure_narrative_sweep_scheduled
from app.workers.handlers import register_all
from app.workers.jobs import WorkerStatus, worker_status
from app.workers.runner import supervised_worker

log = logging.getLogger("api")

# Registration moved to app/workers/handlers.py (task 1.3) so a standalone
# worker can reach it without importing the API — see that module.
register_all()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Floor under the parent-narrative schedule: the sweep re-enqueues itself,
    # but if that row is ever lost (a failure past MAX_ATTEMPTS, a manual purge)
    # every parent narrative stops silently. Re-scheduling it here is idempotent
    # — it does nothing when a sweep is already pending — so a restart heals the
    # schedule without accumulating rows. Best-effort: a database that is not
    # ready must not stop the API from booting.
    try:
        async with async_session() as session:
            await ensure_narrative_sweep_scheduled(session)
            await session.commit()
    except Exception:  # noqa: BLE001 — startup must survive a cold database
        log.exception("could not schedule the narrative sweep at startup")

    # Runs inside the API by default, which is the deployment today. Setting
    # RUN_WORKER_IN_API=false is half of the cutover to a separate worker
    # service (task 1.3) — the other half is actually running one. Flipping it
    # alone stops all background work silently, which is why it is a
    # deliberate setting rather than a default this change quietly alters.
    worker = None
    if get_settings().run_worker_in_api:
        worker = asyncio.create_task(supervised_worker())
    else:
        log.warning(
            "RUN_WORKER_IN_API=false — this process runs no job worker; "
            "a separate worker service must be running or no background work happens"
        )
    yield
    if worker is not None:
        worker.cancel()
        # Awaiting the task we just cancelled is how shutdown waits for it to
        # actually stop; the CancelledError that comes back is the
        # acknowledgement, not a failure.
        with contextlib.suppress(asyncio.CancelledError):
            await worker


#: Sent on every API response. The API returns JSON and file downloads, never
#: HTML meant to be rendered, so this is about how a browser treats a response
#: it was tricked into loading:
#: - nosniff stops a stored upload being re-interpreted as something executable
#:   regardless of the Content-Type we set on it.
#: - The frame-ancestors CSP (and X-Frame-Options for older browsers) keeps API
#:   responses out of an attacker's iframe.
#: - no-referrer keeps ids in request paths out of the Referer header on any
#:   navigation away.
#: The frontend is served separately (static host), so its own headers are set
#: in render.yaml rather than here.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
}

DOCS_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})


#: Cap on the readiness endpoint's database probe. Well under any sensible
#: monitor timeout, so a hung database is reported rather than waited out.
READINESS_DB_TIMEOUT_SECONDS = 5.0


async def _queue_snapshot() -> tuple[dict, datetime | None]:
    """Job counts by status, and when the oldest pending job was queued.

    The aggregate proves connectivity on its own, so there is no separate
    `SELECT 1` — a round-trip that returns rows has already answered the
    question a liveness probe would ask.
    """
    async with async_session() as session:
        counts = await session.execute(select(Job.status, func.count(Job.id)).group_by(Job.status))
        oldest_pending = await session.scalar(
            select(func.min(Job.created_at)).where(Job.status == JobStatus.pending)
        )
    return dict(counts.all()), oldest_pending


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _age_seconds(value: datetime | None) -> float | None:
    """Seconds since `value`, tolerating a naive timestamp.

    SQLite hands back tz-naive datetimes for the same column Postgres returns
    aware, and subtracting one from the other raises. The stored value is UTC
    either way, so assuming UTC on a naive one is a read of the storage
    contract, not a guess.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - value).total_seconds()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            # Swagger UI at /docs pulls its own JS and CSS from a CDN, which
            # `default-src 'none'` would block. The docs are the one HTML page
            # this service serves on purpose, so they opt out of the CSP and
            # keep the rest.
            if header == "Content-Security-Policy" and request.url.path in DOCS_PATHS:
                continue
            response.headers.setdefault(header, value)
        return response

    @app.get("/api/v1/health")
    async def health() -> dict:
        """Liveness: is this process serving HTTP at all?

        Deliberately shallow, and deliberately what render.yaml's
        healthCheckPath polls. Render restarts an instance that fails its health
        check and fails a deploy whose new instance never passes one, so putting
        a database round-trip here would turn a brief database blip into a
        restart loop and a failed deploy. What this endpoint can prove is that
        the container booted, migrations ran, and uvicorn is answering — which
        is exactly what a deploy needs to know and nothing more.

        For "is the system actually working", see /health/ready below.
        """
        return {"status": "ok"}

    @app.get("/api/v1/health/ready")
    async def health_ready(response: Response) -> dict:
        """Readiness: can this instance actually do its job right now?

        Nothing in the platform polls this — it exists so that a human, or an
        external uptime check, can get a straight answer. Before it, a dead job
        worker was completely invisible: the API kept serving, /health kept
        returning a hardcoded "ok", and marking had silently stopped (RISK-4).

        503 means the database is unreachable, or the worker started and then
        stopped turning. Under the test client the worker never starts at all
        (ASGITransport does not run lifespan), which reports as `not_started`
        and is not a failure — a test run is not a broken deployment.
        """
        database: dict = {"ok": False}
        queue: dict | None = None
        try:
            # Bounded, because a refused connection raises promptly but an
            # exhausted pool does not — session.execute() would wait out
            # pool_timeout (30s by default) and a dropped-packet path longer
            # still. An endpoint whose job is to give a straight answer must not
            # hang; a monitor that times out learns nothing, where a 503 with
            # error "TimeoutError" says exactly what is wrong.
            by_status, oldest_pending = await asyncio.wait_for(
                _queue_snapshot(), timeout=READINESS_DB_TIMEOUT_SECONDS
            )
            database = {"ok": True}
            queue = {
                "pending": by_status.get(JobStatus.pending, 0),
                "running": by_status.get(JobStatus.running, 0),
                "failed": by_status.get(JobStatus.failed, 0),
                "oldest_pending_age_seconds": _age_seconds(oldest_pending),
            }
        except Exception as exc:  # noqa: BLE001 — the failure is the answer
            log.exception("readiness check could not reach the database")
            database = {"ok": False, "error": exc.__class__.__name__}

        try:
            # Bounded for the same reason as the queue snapshot above: a
            # database that is unreachable rather than merely slow leaves
            # database["ok"] False regardless, so this still reports 503 —
            # it just does so without waiting out the pool.
            worker = await asyncio.wait_for(worker_status(), timeout=READINESS_DB_TIMEOUT_SECONDS)
        except TimeoutError:
            log.exception("worker status read timed out")
            worker = WorkerStatus(
                state="not_started",
                started_at=None,
                last_loop_at=None,
                seconds_since_loop=None,
                job_running_seconds=None,
                restarts_in_window=0,
                last_restart_at=None,
            )
        ok = database["ok"] and worker.healthy
        if not ok:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if ok else "degraded",
            "database": database,
            "worker": {
                "state": worker.state,
                "started_at": _iso(worker.started_at),
                "last_loop_at": _iso(worker.last_loop_at),
                "seconds_since_loop": worker.seconds_since_loop,
                "job_running_seconds": worker.job_running_seconds,
                "restarts_in_window": worker.restarts_in_window,
                "last_restart_at": _iso(worker.last_restart_at),
            },
            "queue": queue,
        }

    for router in (
        auth.router,
        ai_usage.router,
        analytics.router,
        assessments.router,
        assignments.router,
        classifieds.router,
        grade_boundaries.router,
        groups.router,
        lessons.router,
        me.router,
        narrative.router,
        past_papers.router,
        preferences.router,
        readiness.router,
        readiness_v2.router,
        readiness_weights.router,
        reports.router,
        resources.router,
        students.router,
        subjects.router,
        submissions.router,
        syllabus_uploads.router,
        today.router,
    ):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
