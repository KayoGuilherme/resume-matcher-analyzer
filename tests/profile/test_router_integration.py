import os
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient]:
    """Real app, real settings and database, with the profile table emptied around each test."""
    # Fail loudly: a misconfigured integration job must not pass by skipping.
    if not os.environ.get("DATABASE_URL"):
        pytest.fail("DATABASE_URL must be set for integration tests")
    get_settings.cache_clear()
    engine = get_engine(get_settings())

    async def clear() -> None:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM candidate_profile"))

    await clear()
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    await clear()
    await engine.dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


def _body(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "target_role": "Backend Developer",
        "seniority": "mid",
        "total_years_coding": 5,
        "stacks": [
            {"name": "Postgres", "years": 3, "level": "proficient", "last_year_used": 2024},
            {"name": "Go", "years": 0.5, "level": "learning"},
        ],
        "languages": [{"name": "Português", "level": "native"}, {"name": "en", "level": "B2"}],
        "notable_facts": ["Built a payments API"],
    }
    data.update(overrides)
    return data


async def test_put_then_get_returns_the_normalized_profile(client: httpx.AsyncClient) -> None:
    put = await client.put("/profile", json=_body())
    get = await client.get("/profile")

    assert put.status_code == get.status_code == 200
    assert get.json() == put.json()
    stored = get.json()
    assert [(s["name"], s["original_name"]) for s in stored["stacks"]] == [
        ("postgresql", "Postgres"),
        ("go", "Go"),
    ]
    assert [(i["name"], i["original_name"]) for i in stored["languages"]] == [
        ("portuguese", "Português"),
        ("english", "en"),
    ]
    assert stored["stacks"][1]["last_year_used"] is None


async def test_second_put_replaces_the_first(client: httpx.AsyncClient) -> None:
    await client.put("/profile", json=_body())

    await client.put("/profile", json=_body(target_role="Data Engineer", stacks=[]))

    stored = (await client.get("/profile")).json()
    assert stored["target_role"] == "Data Engineer"
    assert stored["stacks"] == []


async def test_rejected_put_leaves_the_stored_profile_unchanged(client: httpx.AsyncClient) -> None:
    first = await client.put("/profile", json=_body())

    bad_field = await client.put("/profile", json=_body(seniority="principal"))
    bad_rule = await client.put("/profile", json=_body(total_years_coding=1))

    assert bad_field.status_code == bad_rule.status_code == 422
    assert (await client.get("/profile")).json() == first.json()


async def test_get_without_a_profile_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/profile")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "profile_not_found"
