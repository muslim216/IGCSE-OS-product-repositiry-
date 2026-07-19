from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, groups, me, students, subjects
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")

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

    for router in (auth.router, groups.router, me.router, students.router, subjects.router):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
