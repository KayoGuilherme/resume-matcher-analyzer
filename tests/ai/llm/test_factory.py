from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI
from pydantic import BaseModel

from app.ai.errors import AINotConfiguredError
from app.ai.llm import FakeLLMClient, LLMClient, get_llm_client
from app.ai.llm.anthropic_client import AnthropicTransport
from app.ai.llm.factory import _client_for
from app.ai.llm.openai_client import OpenAITransport
from app.ai.llm.structured import StructuredLLM
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers

DB = "postgresql+asyncpg://u:p@localhost:5432/x"


def _settings(**values: Any) -> Settings:
    return Settings(database_url=DB, **values)


def test_anthropic_is_built_from_the_settings() -> None:
    client = get_llm_client(_settings(llm_provider="anthropic", llm_model="m1", llm_api_key="k"))

    assert isinstance(client, StructuredLLM)
    assert isinstance(client.transport, AnthropicTransport)
    assert (client.provider, client.model) == ("anthropic", "m1")


def test_openai_is_built_from_the_settings() -> None:
    client = get_llm_client(_settings(llm_provider="openai", llm_model="m2", llm_api_key="k"))

    assert isinstance(client, StructuredLLM)
    assert isinstance(client.transport, OpenAITransport)
    assert (client.provider, client.model) == ("openai", "m2")


def test_a_compatible_server_works_without_a_key() -> None:
    client = get_llm_client(
        _settings(
            llm_provider="openai_compatible",
            llm_model="llama3.1",
            llm_base_url="http://localhost:11434/v1",
        )
    )

    assert isinstance(client, StructuredLLM)
    assert isinstance(client.transport, OpenAITransport)
    assert client.provider == "openai_compatible"


def test_switching_the_provider_setting_changes_the_adapter_and_nothing_else() -> None:
    common = {"llm_model": "m", "llm_api_key": "k", "llm_base_url": "http://localhost:1/v1"}

    hosted = get_llm_client(_settings(llm_provider="anthropic", **common))
    local = get_llm_client(_settings(llm_provider="openai_compatible", **common))

    assert type(hosted.transport) is AnthropicTransport  # type: ignore[attr-defined]
    assert type(local.transport) is OpenAITransport  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("values", "missing"),
    [
        ({}, "LLM_PROVIDER"),
        ({"llm_provider": "anthropic", "llm_api_key": "k"}, "LLM_MODEL"),
        ({"llm_provider": "openai", "llm_model": "m"}, "LLM_API_KEY"),
        ({"llm_provider": "openai", "llm_model": "m", "llm_api_key": ""}, "LLM_API_KEY"),
        ({"llm_provider": "anthropic", "llm_model": "m"}, "LLM_API_KEY"),
        ({"llm_provider": "openai_compatible", "llm_model": "m"}, "LLM_BASE_URL"),
    ],
)
def test_missing_settings_are_named_and_no_value_is_echoed(
    values: dict[str, Any], missing: str
) -> None:
    with pytest.raises(AINotConfiguredError) as exc_info:
        get_llm_client(_settings(**values))

    assert missing in exc_info.value.message
    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "ai_not_configured"


def test_the_client_is_cached_per_settings() -> None:
    settings = _settings(llm_provider="openai", llm_model="m", llm_api_key="k")

    assert get_llm_client(settings) is get_llm_client(settings)
    assert _client_for(settings) is get_llm_client(settings)
    other = _settings(llm_provider="openai", llm_model="other", llm_api_key="k")
    assert get_llm_client(other) is not get_llm_client(settings)


class Answer(BaseModel):
    text: str


async def test_the_dependency_can_be_replaced_by_a_fake_through_fastapi() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/ask")
    async def ask(llm: LLMClient = Depends(get_llm_client)) -> dict[str, str]:  # noqa: B008
        return {"answer": (await llm.generate_structured("hi", Answer)).text}

    app.dependency_overrides[get_settings] = lambda: _settings()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unconfigured = await client.get("/ask")
        app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient([Answer(text="fake")])
        replaced = await client.get("/ask")

    assert unconfigured.status_code == 503
    assert unconfigured.json()["error"]["code"] == "ai_not_configured"
    assert replaced.json() == {"answer": "fake"}
