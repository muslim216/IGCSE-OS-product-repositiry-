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
    classroom,
    grade_boundaries,
    groups,
    knowledge,
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
from app.services.ai import AIUnavailableError, resolve_surface
from app.services.extraction import extract_assignment, extract_past_paper
from app.services.google_classroom import sync_classroom
from app.services.marking import mark_submission
from app.services.narrative import (
    CLASS_NARRATIVE_JOB,
    SWEEP_JOB,
    ensure_narrative_sweep_scheduled,
    generate_narrative,
    sweep_parent_narratives,
)
from app.services.readiness import recompute_student
from app.services.readiness_v2_ai import compute_readiness_v2
from app.services.reports import generate_report
from app.services.syllabus_extraction import extract_syllabus
from app.workers.jobs import (
    note_worker_restart,
    register_handler,
    worker_loop,
    worker_status,
)

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
# The stored narrative (services/narrative.py). The class paragraph is enqueued
# from the tail of the evidence build; the parent paragraph by a weekly sweep
# that re-derives who is due and re-enqueues itself — never a self-perpetuating
# per-student chain, whose schedule would die with one failed job row.
register_handler(CLASS_NARRATIVE_JOB, generate_narrative)
register_handler(SWEEP_JOB, sweep_parent_narratives)


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
        # Counted, not just logged. worker_loop() re-stamps its liveness clock on
        # entry, so without this a loop that raises immediately and restarts every
        # few seconds reports `running` forever while completing no work — the one
        # failure readiness exists to catch, hidden by the fix for the other one.
        note_worker_restart()
        await asyncio.sleep(WORKER_RESTART_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Chat is the only streaming surface, and streaming is Anthropic-only.
    # Routing it to Gemini used to be a config mistake nobody saw until a
    # student opened chat and the stream failed at request time. Checked here
    # too, not just inside the worker loop, so it shows up in the boot log
    # instead of the first support ticket. Logged, not raised: AI-20 says a
    # misconfigured surface degrades with a clear message, and must never
    # block the API from starting.
    try:
        resolve_surface("chat", require_streaming=True)
    except AIUnavailableError as exc:
        log.error("chat is misconfigured at startup: %s", exc)

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

    worker = asyncio.create_task(_supervised_worker())
    yield
    worker.cancel()
    # Awaiting the task we just cancelled is how shutdown waits for it to
    # actually stop; the CancelledError that comes back is the acknowledgement,
    # not a failure.
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
        classroom.router,
        grade_boundaries.router,
        groups.router,
        knowledge.router,
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
