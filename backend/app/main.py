import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text

from app.api import (
    ai_usage,
    analytics,
    assessments,
    assignments,
    auth,
    chat,
    classifieds,
    classroom,
    groups,
    knowledge,
    lessons,
    me,
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
)
from app.config import get_settings
from app.db import async_session
from app.models import Job, JobStatus
from app.services.extraction import extract_assignment, extract_past_paper
from app.services.google_classroom import sync_classroom
from app.services.marking import mark_submission
from app.services.readiness import recompute_student
from app.services.readiness_v2_ai import compute_readiness_v2
from app.services.reports import generate_report
from app.services.syllabus_extraction import extract_syllabus
from app.workers.jobs import register_handler, worker_loop, worker_status

log = logging.getLogger("api")

register_handler("extract_assignment", extract_assignment)
# A past paper is a full-paper classified: same extractor, same prompt.
register_handler("extract_past_paper", extract_past_paper)
register_handler("mark_submission", mark_submission)
register_handler("recompute_readiness", recompute_student)
# Readiness v2 is what the readiness UI/API serve (services/readiness_summary_v2.py),
# falling back to v1 for any (student, subject) with no snapshot yet. Runs are
# enqueued debounced per (student, subject) so a burst of auto-finalized
# submissions costs one synthesis, not one each.
register_handler("compute_readiness_v2", compute_readiness_v2)
register_handler("generate_report", generate_report)
register_handler("extract_syllabus", extract_syllabus)
# Polling sync: imports courseWork/submissions from every course a tutor has
# linked (api/classroom.py). Enqueued on demand today; a future scheduler
# can call the same job type periodically with no handler changes.
register_handler("sync_classroom", sync_classroom)


#: Pause before restarting a worker that died, so a failure that recurs
#: immediately (a bad DB URL, say) logs at a readable rate instead of spinning.
WORKER_RESTART_SECONDS = 5.0


async def _supervised_worker() -> None:
    """Keep the job worker running for the whole life of the process.

    worker_loop() already survives any individual job failing, but nothing
    survived the loop itself ending: the task was created and never looked at
    again, so an exception escaping it left the API serving requests normally
    with no background work happening at all and no signal that anything had
    changed. Extraction, marking, readiness synthesis, reports and Classroom
    sync all stop together, and the only visible symptom is homework that stays
    "processing" forever (RISK-4).
    """
    while True:
        try:
            await worker_loop()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — supervising means surviving anything
            log.exception("job worker died; restarting in %ss", WORKER_RESTART_SECONDS)
        else:
            # worker_loop() loops forever, so a clean return is itself a bug.
            log.error("job worker returned unexpectedly; restarting in %ss", WORKER_RESTART_SECONDS)
        await asyncio.sleep(WORKER_RESTART_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = asyncio.create_task(_supervised_worker())
    yield
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass


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
            async with async_session() as session:
                await session.execute(text("SELECT 1"))
                counts = await session.execute(
                    select(Job.status, func.count(Job.id)).group_by(Job.status)
                )
                by_status = dict(counts.all())
                oldest_pending = await session.scalar(
                    select(func.min(Job.created_at)).where(Job.status == JobStatus.pending)
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

        worker = worker_status()
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
            },
            "queue": queue,
        }

    for router in (
        auth.router,
        ai_usage.router,
        analytics.router,
        assessments.router,
        assignments.router,
        chat.router,
        classifieds.router,
        classroom.router,
        groups.router,
        knowledge.router,
        lessons.router,
        me.router,
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
    ):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
