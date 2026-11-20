from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.profile.router import get_profile_service
from app.profile.schemas import ProfileOut
from app.profile.service import ProfileService


class MemoryRepository:
    def __init__(self) -> None:
        self.stored: ProfileOut | None = None

    async def get(self) -> ProfileOut | None:
        return self.stored

    async def save(self, profile: ProfileOut) -> None:
        self.stored = profile


@pytest.fixture
def client_app(app: FastAPI) -> FastAPI:
    service = ProfileService(MemoryRepository())  # type: ignore[arg-type]
    app.dependency_overrides[get_profile_service] = lambda: service
    return app


def _body(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "target_role": "Backend Developer",
        "seniority": "mid",
        "total_years_coding": 5,
        "stacks": [{"name": "Springboot", "years": 3, "level": "working", "last_year_used": 2024}],
        "languages": [{"name": "pt", "level": "native"}],
        "notable_facts": ["Built a payments API"],
    }
    data.update(overrides)
    return data


async def _request(app: FastAPI, method: str, json: Any = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, "/profile", json=json)


async def test_put_returns_the_normalized_profile(client_app: FastAPI) -> None:
    response = await _request(client_app, "PUT", _body())

    assert response.status_code == 200
    assert response.json() == {
        "target_role": "Backend Developer",
        "seniority": "mid",
        "total_years_coding": 5.0,
        "stacks": [
            {
                "name": "spring boot",
                "original_name": "Springboot",
                "years": 3.0,
                "level": "working",
                "last_year_used": 2024,
            }
        ],
        "languages": [{"name": "portuguese", "original_name": "pt", "level": "native"}],
        "notable_facts": ["Built a payments API"],
    }


async def test_get_returns_what_put_stored(client_app: FastAPI) -> None:
    put = await _request(client_app, "PUT", _body())

    get = await _request(client_app, "GET")

    assert get.status_code == 200
    assert get.json() == put.json()


async def test_put_replaces_the_previous_profile(client_app: FastAPI) -> None:
    await _request(client_app, "PUT", _body())

    await _request(client_app, "PUT", _body(stacks=[], target_role="Data Engineer"))

    stored = (await _request(client_app, "GET")).json()
    assert stored["stacks"] == []
    assert stored["target_role"] == "Data Engineer"


async def test_get_without_a_profile_is_404_with_the_error_envelope(client_app: FastAPI) -> None:
    response = await _request(client_app, "GET")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "profile_not_found"


async def test_schema_violations_are_422_validation_errors(client_app: FastAPI) -> None:
    response = await _request(
        client_app,
        "PUT",
        _body(seniority="principal", stacks=[{"name": "Go", "years": -1, "level": "working"}]),
    )

    error = response.json()["error"]
    assert response.status_code == 422
    assert error["code"] == "validation_error"
    assert "seniority: " in error["message"]
    assert "stacks[0].years: " in error["message"]
    assert "principal" not in response.text


async def test_rule_violations_are_422_invalid_profile(client_app: FastAPI) -> None:
    stacks = [{"name": "Go", "years": 9, "level": "working"}]

    response = await _request(client_app, "PUT", _body(stacks=stacks))

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_profile",
            "message": "stacks[0]: years exceed total_years_coding",
        }
    }


async def test_rejected_put_keeps_the_previous_profile(client_app: FastAPI) -> None:
    first = await _request(client_app, "PUT", _body())

    await _request(client_app, "PUT", _body(seniority="principal"))
    await _request(client_app, "PUT", _body(total_years_coding=0))

    assert (await _request(client_app, "GET")).json() == first.json()


async def test_a_get_body_is_not_accepted_by_put(client_app: FastAPI) -> None:
    put = await _request(client_app, "PUT", _body())

    response = await _request(client_app, "PUT", put.json())

    assert response.status_code == 422
    assert "stacks[0].original_name: " in response.json()["error"]["message"]
