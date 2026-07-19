import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    analytics,
    assessments,
    assignments,
    auth,
    chat,
    classifieds,
    groups,
    me,
    readiness,
    reports,
    students,
    subjects,
    submissions,
)
from app.config import get_settings
from app.services.extraction import extract_assignment
from app.services.marking import mark_submission
from app.services.readiness import recompute_student
from app.services.reports import generate_report
from app.workers.jobs import register_handler, worker_loop

register_handler("extract_assignment", extract_assignment)
register_handler("mark_submission", mark_submission)
register_handler("recompute_readiness", recompute_student)
register_handler("generate_report", generate_report)


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
        analytics.router,
        assessments.router,
        assignments.router,
        chat.router,
        classifieds.router,
        groups.router,
        me.router,
        readiness.router,
        reports.router,
        students.router,
        subjects.router,
        submissions.router,
    ):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
