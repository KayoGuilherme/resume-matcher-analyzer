import logging

import pytest
from fastapi import FastAPI

from app.core.config import get_settings
from app.main import create_app, lifespan


def test_app_exposes_health_route() -> None:
    assert "/health" in create_app().openapi()["paths"]


async def test_lifespan_configures_logging_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[object] = []
    jobs_started: list[object] = []

    async def fake_startup(settings: object) -> None:
        started.append(settings)

    async def fake_jobs_startup(settings: object) -> None:
        jobs_started.append(settings)

    monkeypatch.setattr("app.main.run_startup", fake_startup)
    monkeypatch.setattr("app.main.run_jobs_startup", fake_jobs_startup)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/x")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    get_settings.cache_clear()
    try:
        async with lifespan(FastAPI()):
            assert logging.getLogger().level == logging.ERROR
            # the startup checks run once each, after logging is set up
            assert (len(started), len(jobs_started)) == (1, 1)
    finally:
        get_settings.cache_clear()
