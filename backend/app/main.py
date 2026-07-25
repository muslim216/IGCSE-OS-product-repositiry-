import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from app.services.extraction import extract_assignment, extract_past_paper
from app.services.google_classroom import sync_classroom
from app.services.marking import mark_submission
from app.services.readiness import recompute_student
from app.services.readiness_v2_ai import compute_readiness_v2
from app.services.reports import generate_report
from app.services.syllabus_extraction import extract_syllabus
from app.workers.jobs import register_handler, worker_loop

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = asyncio.create_task(worker_loop())
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
        return {"status": "ok"}

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
