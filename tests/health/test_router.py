import asyncio
from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI

from app.core.db import get_session
from app.health import router as health_router


class FakeSession:
    def __init__(self, error: Exception | None = None, delay: float = 0.0) -> None:
        self._error = error
        self._delay = delay

    async def execute(self, *_: object) -> None:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error


def _override(app: FastAPI, session: FakeSession) -> None:
    async def fake() -> AsyncGenerator[FakeSession]:
        yield session

    app.dependency_overrides[get_session] = fake


async def _get(app: FastAPI) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health")


async def test_health_ok_when_database_reachable(app: FastAPI) -> None:
    _override(app, FakeSession())

    response = await _get(app)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_health_503_when_database_fails_and_hides_details(app: FastAPI) -> None:
    _override(app, FakeSession(error=ConnectionError("postgresql://user:secret@db:5432/ats")))

    response = await _get(app)

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}
    assert "secret" not in response.text
    assert "postgresql" not in response.text


async def test_health_503_when_database_is_slow(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_router, "DB_CHECK_TIMEOUT_SECONDS", 0.05)
    _override(app, FakeSession(delay=1.0))

    response = await _get(app)

    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"
