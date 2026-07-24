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
    preferences,
    readiness,
    readiness_v2,
    reports,
    resources,
    students,
    subjects,
    submissions,
    syllabus_uploads,
)
from app.config import get_settings
from app.services.extraction import extract_assignment
from app.services.google_classroom import sync_classroom
from app.services.marking import mark_submission
from app.services.readiness import recompute_student
from app.services.readiness_v2_ai import compute_readiness_v2
from app.services.reports import generate_report
from app.services.syllabus_extraction import extract_syllabus
from app.workers.jobs import register_handler, worker_loop

register_handler("extract_assignment", extract_assignment)
register_handler("mark_submission", mark_submission)
register_handler("recompute_readiness", recompute_student)
# Readiness v2 shadow-runs alongside v1 whenever settings.readiness_v2_shadow_enabled
# is on (enqueue_v2_shadow, called next to every recompute_readiness enqueue).
# v1 still drives every existing endpoint; GET /readiness/v2/... is a
# separate, read-only comparison surface (see api/readiness_v2.py).
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
        preferences.router,
        readiness.router,
        readiness_v2.router,
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
