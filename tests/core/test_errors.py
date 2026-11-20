from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.core.errors import DomainError, register_error_handlers


class Item(BaseModel):
    name: str = Field(min_length=1)
    years: int = Field(ge=0)


class Payload(BaseModel):
    role: str = Field(max_length=5)
    items: list[Item]


class TeapotError(DomainError):
    status_code = 418
    code = "teapot"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/domain")
    async def domain() -> None:
        raise TeapotError("I am a teapot")

    @app.get("/base")
    async def base() -> None:
        raise DomainError("generic failure")

    @app.put("/payload")
    async def payload(body: Payload) -> None:
        return None

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail postgresql://u:p@db/x")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_domain_error_is_mapped_to_status_code_and_json(client: httpx.AsyncClient) -> None:
    response = await client.get("/domain")

    assert response.status_code == 418
    assert response.json() == {"error": {"code": "teapot", "message": "I am a teapot"}}


async def test_base_domain_error_has_non_success_default_status(client: httpx.AsyncClient) -> None:
    response = await client.get("/base")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "domain_error"


async def test_unexpected_exception_returns_generic_500(client: httpx.AsyncClient) -> None:
    response = await client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error"}
    }
    assert "secret" not in response.text


async def test_validation_error_uses_the_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.put(
        "/payload", json={"role": "dev", "items": [{"name": "a", "years": -1}]}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"].startswith("items[0].years: ")
    assert "body" not in error["message"]


async def test_validation_error_names_every_invalid_field(client: httpx.AsyncClient) -> None:
    response = await client.put(
        "/payload", json={"role": "far too long", "items": [{"name": "", "years": -1}]}
    )

    message = response.json()["error"]["message"]
    assert response.status_code == 422
    assert "role: " in message
    assert "items[0].name: " in message
    assert "items[0].years: " in message


async def test_validation_error_does_not_echo_submitted_values(client: httpx.AsyncClient) -> None:
    private_text = "PRIVATE-resume-text-123"
    response = await client.put(
        "/payload",
        json={"role": private_text, "items": [{"name": private_text, "years": private_text}]},
    )

    assert response.status_code == 422
    assert private_text not in response.text
    assert "input" not in response.json()["error"]


async def test_malformed_json_is_reported_without_a_field_name(client: httpx.AsyncClient) -> None:
    response = await client.put(
        "/payload", content=b"{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["message"].startswith("request body: ")
