import os
from collections.abc import AsyncGenerator

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.core.db import get_engine, get_sessionmaker
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
async def real_settings() -> AsyncGenerator[Settings]:
    """Settings read from the environment, with the cached engine disposed afterwards."""
    # Fail loudly: a misconfigured integration job must not pass by skipping.
    if not os.environ.get("DATABASE_URL"):
        pytest.fail("DATABASE_URL must be set for integration tests")
    get_settings.cache_clear()
    settings = get_settings()
    yield settings
    await get_engine(settings).dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


async def test_health_reports_database_ok_against_real_database(real_settings: Settings) -> None:
    app = create_app()  # no dependency overrides: real Settings, real engine, real session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
