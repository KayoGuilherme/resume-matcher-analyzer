"""Application factory. Wiring only, no logic."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.health.router import router as health_router
from app.profile.router import router as profile_router
from app.resumes.router import router as resumes_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().log_level)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="ATS Resume Analyzer", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(profile_router)
    app.include_router(resumes_router)
    return app


app = create_app()
