# git test
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app import log_context
from app.api import (
    ai_usage,
    analytics,
    assessments,
    assignments,
    auth,
    booklets,
    classifieds,
    custom_criteria,
    dismissals,
    grade_boundaries,
    groups,
    integrations,
    lessons,
    marking_rules,
    me,
    mistake_categories,
    mocks,
    narrative,
    notifications,
    onboarding,
    past_papers,
    readiness,
    readiness_v2,
    readiness_weights,
    reports,
    resources,
    students,
    subjects,
    submissions,
    syllabus_uploads,
    teaching_guidance,
    teaching_plans,
    today,
    webhooks,
    weekly_sends,
)
from app.body_limit import BodySizeLimit
from app.config import get_settings
from app.db import async_session, pool_status
from app.models import Job, JobStatus
from app.services.ai import SURFACES, AiProvider, resolve_surface
from app.services.lesson_autorecord import ensure_lesson_autorecord_scheduled
from app.services.narrative import ensure_narrative_sweep_scheduled
from app.services.notifications.triggers import ensure_message_trigger_sweep_scheduled
from app.services.past_paper_phase import ensure_past_paper_phase_sweep_scheduled
from app.services.rate_limit import close_all_limiters, rate_limit_health
from app.services.retention import ensure_retention_sweep_scheduled
from app.services.weekly_send import ensure_weekly_send_sweep_scheduled
from app.workers.handlers import register_all
from app.workers.jobs import WorkerStatus, worker_status
from app.workers.runner import supervised_worker

log = logging.getLogger("api")

# Registration moved to app/workers/handlers.py (task 1.3) so a standalone
# worker can reach it without importing the API — see that module.
register_all()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # First, so everything below is logged with a time, a level and its
    # request or job (`app/log_context.py`). Here rather than at import, so the
    # test suite's own log capture is left alone.
    log_context.configure_logging()
    # Marks this process as a real deployment for /health/ready: a worker that
    # has still not started a minute after this is a failure, not a test
    # harness (see WORKER_START_GRACE_SECONDS).
    app.state.serving_since = datetime.now(timezone.utc)
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

    # Same floor for the past-paper-phase recompute (AV-31): the sweep re-arms
    # itself, and this heals the schedule if that row is ever lost.
    try:
        async with async_session() as session:
            await ensure_past_paper_phase_sweep_scheduled(session)
            await session.commit()
    except Exception:  # noqa: BLE001 — startup must survive a cold database
        log.exception("could not schedule the past-paper-phase sweep at startup")

    # The same floor under the plan auto-record sweep (AV-119): it re-arms itself,
    # and a lost row would stop lessons counting as taught without a sound.
    try:
        async with async_session() as session:
            await ensure_lesson_autorecord_scheduled(session)
            await session.commit()
    except Exception:  # noqa: BLE001 — startup must survive a cold database
        log.exception("could not schedule the lesson auto-record sweep at startup")

    # And under the weekly send (task 8.2): a lost sweep row would stop every
    # account's weekly report, and nobody is told when a report does not arrive.
    try:
        async with async_session() as session:
            await ensure_weekly_send_sweep_scheduled(session)
            await session.commit()
    except Exception:  # noqa: BLE001 — startup must survive a cold database
        log.exception("could not schedule the weekly send sweep at startup")
    # And under the message reminders (task 8.5): a lost sweep row would stop
    # every lesson reminder and homework nudge with nothing to show for it.
    try:
        async with async_session() as session:
            await ensure_message_trigger_sweep_scheduled(session)
            await session.commit()
    except Exception:  # noqa: BLE001 — startup must survive a cold database
        log.exception("could not schedule the message trigger sweep at startup")
    # And under retention: a lost sweep row would let old rows and orphaned
    # files pile up until the disk is full, which is the failure it prevents.
    try:
        async with async_session() as session:
            await ensure_retention_sweep_scheduled(session)
            await session.commit()
    except Exception:  # noqa: BLE001 — startup must survive a cold database
        log.exception("could not schedule the retention sweep at startup")

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

    # Best-effort, and after the worker: a pool that will not close must not
    # stop the process exiting, and shutdown is not the moment to raise.
    try:
        await close_all_limiters()
    except Exception:  # noqa: BLE001 — shutdown must complete regardless
        log.exception("could not close the rate limiter's Redis pool")


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

#: Only served off Render: a deployment registers no docs routes (SA-12).
DOCS_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})


#: How long after the process starts serving a missing worker is still
#: believed to be starting up. Past it, `not_started` on a deployment is the
#: silent stop: an API serving happily while no background work ever runs.
WORKER_START_GRACE_SECONDS = 60.0

#: How far back /health/ready counts failed jobs, by when they were queued.
#: Reported, not judged: a single unreadable upload fails for good and is not
#: an outage.
FAILED_WINDOW = timedelta(hours=24)

#: Cap on the readiness endpoint's database probe. Well under any sensible
#: monitor timeout, so a hung database is reported rather than waited out.
READINESS_DB_TIMEOUT_SECONDS = 5.0


async def _queue_snapshot() -> dict:
    """Job counts by status, and the ages /health/ready judges.

    The aggregate proves connectivity on its own, so there is no separate
    `SELECT 1`: a round-trip that returns rows has already answered the
    question a liveness probe would ask.

    `oldest_due` is when the longest-waiting job that may run now became due
    (its `run_after`, or when it was queued). `oldest_pending` counts jobs
    scheduled for later too (the weekly sweeps, a retry waiting out its
    backoff), so it is up to a day old on a healthy system and useless for an
    alert.
    """
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        counts = await session.execute(select(Job.status, func.count(Job.id)).group_by(Job.status))
        oldest_pending = await session.scalar(
            select(func.min(Job.created_at)).where(Job.status == JobStatus.pending)
        )
        oldest_due = await session.scalar(
            select(func.min(func.coalesce(Job.run_after, Job.created_at))).where(
                Job.status == JobStatus.pending,
                or_(Job.run_after.is_(None), Job.run_after <= now),
            )
        )
        failed_recently = await session.scalar(
            select(func.count(Job.id)).where(
                Job.status == JobStatus.failed, Job.created_at >= now - FAILED_WINDOW
            )
        )
    return {
        "by_status": dict(counts.all()),
        "oldest_pending": oldest_pending,
        "oldest_due": oldest_due,
        "failed_recently": failed_recently or 0,
    }


def _ai_keys() -> dict:
    """Whether every AI provider a surface is routed to has its key.

    A missing key never blocks startup (`AI-20`): each surface degrades with a
    clear message. But with the key gone nothing is marked, read or written,
    and the only sign was each failure arriving one at a time; 15 of the 18
    failed jobs found in production in October were this.
    """
    settings = get_settings()
    # `<provider>_api_key` for every provider, so a new one cannot be
    # reported as missing for want of an entry here.
    keys = {p: getattr(settings, f"{p.value}_api_key", None) for p in AiProvider}
    try:
        routed = {resolve_surface(surface)[0] for surface in SURFACES}
    except ValueError:
        # A misspelt provider is a configuration fault every AI call would hit.
        # Its message echoes the setting's raw value, which could be a key
        # pasted into the wrong field, so it goes neither to this public answer
        # nor to the log this endpoint writes on every poll; the AI call that
        # hits it raises it in full.
        log.error("an AI surface is routed to a provider that does not exist; check AI_*_PROVIDER")
        return {"ok": False, "error": "provider_misconfigured"}
    missing = sorted(p.value for p in routed if not (keys.get(p) or "").strip())
    return {"ok": not missing, "missing_keys": missing}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def _worker_snapshot() -> WorkerStatus:
    """The worker half of /health/ready, bounded and never fatal.

    Bounded for the same reason as the queue probe, and separately from it:
    this is a second database read, so a pool that is exhausted rather than
    refused would hang here having sailed past that timeout.

    An unreadable worker table reports `unknown`, which is not healthy — "no
    idea" must not be answered with the 200 that "no workers yet" legitimately
    gets.
    """
    try:
        return await asyncio.wait_for(worker_status(), timeout=READINESS_DB_TIMEOUT_SECONDS)
    # The failure is the answer.
    except Exception:  # noqa: BLE001
        log.exception("readiness check could not read worker status")
        return WorkerStatus(
            state="unknown",
            started_at=None,
            last_loop_at=None,
            seconds_since_loop=None,
            job_running_seconds=None,
            restarts_in_window=0,
            last_restart_at=None,
        )


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


async def _request_context(request, call_next):
    """Tag every log line of a request with its id, and return the id, so a
    problem someone reports can be found in the log (OPS-06). Always made
    here: a caller choosing its own could make its lines collide with someone
    else's in a search.

    An unhandled error is logged here, while the request's id is still bound,
    and then left to propagate as before: the server answers it with its own
    500, which carries no id, but the log line that explains it does. Turning
    it into our own response would also hide it from anything below the
    server that relies on the exception (the test client among them).
    """
    rid = log_context.new_request_id()
    token = log_context.bind(f"req-{rid}")
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error in %s %s", request.method, request.url.path)
        raise
    finally:
        log_context.reset(token)
    response.headers["X-Request-ID"] = rid
    return response


#: What a turned-away request is told to wait before trying again.
BUSY_RETRY_AFTER_SECONDS = 5


def _busy(request: Request, exc: Exception) -> JSONResponse:
    """Every database connection stayed taken for `POOL_TIMEOUT_SECONDS`. Say so
    plainly with a 503 and Retry-After instead of a bare 500, so a page can try
    again and the logs show load, not a bug (`CAP-16`)."""
    # The pool's counts, so a leak (full while traffic is light) can be told
    # from load; the request id is already on the line.
    log.warning(
        "turned away %s %s: no database connection free (pool %s): %s",
        request.method,
        request.url.path,
        pool_status(),
        exc,
    )
    return JSONResponse(
        {"detail": "Avora is busy right now. Please try again in a moment."},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        headers={"Retry-After": str(BUSY_RETRY_AFTER_SECONDS)},
    )


def create_app() -> FastAPI:
    settings = get_settings()
    # SA-12: a real deployment does not publish its route map. Only the URLs
    # go; app.openapi() still works for the snapshot test and type generation.
    docs_off = {"docs_url": None, "redoc_url": None, "openapi_url": None} if settings.render else {}
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan, **docs_off)

    # Innermost of the middleware, so a 413 still carries CORS, the request id
    # and the security headers that the layers added after it put on.
    app.add_middleware(
        BodySizeLimit,
        max_upload_bytes=settings.max_upload_request_mb * 1024 * 1024,
        openapi=app.openapi,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    app.middleware("http")(_request_context)
    app.add_exception_handler(PoolTimeoutError, _busy)

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

        503 means the database is unreachable, the worker started and then
        stopped turning, a configured Redis has stopped answering and login
        throttling has silently degraded to per-instance (task 1.4, AV-83), an
        AI provider a surface is routed to has no key, the sign-in secret is the
        public placeholder or too short (`SA-04`), or this process has been
        serving for over a minute with no worker anywhere (cleanup stage,
        OPS-05). Under the test client the lifespan never runs
        (ASGITransport does not run it), so the worker reports `not_started`
        and that is not a failure: a test run is not a broken deployment.
        Recently queued work that failed (`failed_queued_last_24h`) and how long
        due work has waited (`oldest_due_age_seconds`) are reported, not judged.
        """
        database: dict = {"ok": False}
        queue: dict | None = None
        try:
            # Bounded, because a refused connection raises promptly but an
            # exhausted pool does not — session.execute() would wait out
            # pool_timeout (`POOL_TIMEOUT_SECONDS`, 10s) and a dropped-packet
            # path longer still. The pool's counts in the answer tell the two
            # apart. An endpoint whose job is to give a straight answer must not
            # hang; a monitor that times out learns nothing, where a 503 with
            # error "TimeoutError" says exactly what is wrong.
            snapshot = await asyncio.wait_for(
                _queue_snapshot(), timeout=READINESS_DB_TIMEOUT_SECONDS
            )
            database = {"ok": True}
            by_status = snapshot["by_status"]
            oldest_due_age = _age_seconds(snapshot["oldest_due"])
            queue = {
                "pending": by_status.get(JobStatus.pending, 0),
                "running": by_status.get(JobStatus.running, 0),
                "failed": by_status.get(JobStatus.failed, 0),
                # By when the job was queued: the table records no time a job
                # failed, so a job queued days ago that failed just now is not here.
                "failed_queued_last_24h": snapshot["failed_recently"],
                "oldest_pending_age_seconds": _age_seconds(snapshot["oldest_pending"]),
                # Reported, not judged. A queue that is not moving already shows
                # as a stale or stalled worker; a long one that is moving is a
                # backlog (one tutor's batch of uploads), not an outage.
                "oldest_due_age_seconds": oldest_due_age,
            }
        except Exception as exc:  # noqa: BLE001 — the failure is the answer
            log.exception("readiness check could not reach the database")
            database = {"ok": False, "error": exc.__class__.__name__}

        worker = await _worker_snapshot()
        # Bounded internally by the limiter's own REDIS_TIMEOUT_SECONDS, on the
        # same reasoning as the two database reads above: an endpoint whose job
        # is to give a straight answer must not hang. It PINGs rather than
        # reporting what past logins happened to observe, so a fresh instance
        # whose configured Redis is refusing connections says so immediately
        # instead of at the next login attempt (threat review F4). No Redis
        # configured at all is the documented single-instance mode, needs no
        # round trip, and is not degraded.
        rate_limit = await rate_limit_health()
        ai = _ai_keys()
        # A yes or no, never the value. With the placeholder anyone can sign a
        # token for any account (`SA-04`); reported here first so the live
        # value can be checked before startup refuses it.
        auth = {"secret_ok": not get_settings().jwt_secret_is_weak}
        serving_since = getattr(app.state, "serving_since", None)
        worker_missing = (
            worker.state == "not_started"
            and serving_since is not None
            and _age_seconds(serving_since) > WORKER_START_GRACE_SECONDS
        )
        ok = (
            database["ok"]
            and worker.healthy
            and not worker_missing
            and rate_limit["ok"]
            and ai["ok"]
            and auth["secret_ok"]
        )
        if not ok:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if ok else "degraded",
            "database": {**database, "pool": pool_status()},
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
            "rate_limit": rate_limit,
            "ai": ai,
            "auth": auth,
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
        integrations.router,
        integrations.lesson_router,
        lessons.router,
        marking_rules.router,
        me.router,
        mistake_categories.router,
        mocks.router,
        narrative.router,
        notifications.router,
        onboarding.router,
        webhooks.router,
        booklets.router,
        past_papers.router,
        readiness.router,
        readiness_v2.router,
        readiness_weights.router,
        custom_criteria.router,
        dismissals.router,
        reports.router,
        resources.router,
        students.router,
        subjects.router,
        submissions.router,
        syllabus_uploads.router,
        teaching_guidance.router,
        teaching_plans.router,
        today.router,
        weekly_sends.router,
    ):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
