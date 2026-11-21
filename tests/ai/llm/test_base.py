import httpx
from fastapi import FastAPI

from app.ai.errors import AINotConfiguredError
from app.ai.llm.base import (
    LLMAuthError,
    LLMClient,
    LLMError,
    LLMInvalidOutputError,
    LLMTimeoutError,
    LLMTransientError,
)
from app.ai.llm.fake import FakeLLMClient
from app.ai.llm.structured import StructuredLLM
from app.core.errors import register_error_handlers
from tests.ai.llm.transport import ScriptedTransport


async def test_ai_not_configured_renders_503_with_its_code() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/x")
    async def _route() -> None:
        raise AINotConfiguredError("Set LLM_PROVIDER to use this feature")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/x")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "ai_not_configured", "message": "Set LLM_PROVIDER to use this feature"}
    }


def test_every_typed_error_is_an_llm_error_carrying_only_its_message() -> None:
    for error_type in (LLMTransientError, LLMInvalidOutputError, LLMAuthError, LLMTimeoutError):
        error = error_type("failed with status 500")
        assert isinstance(error, LLMError)
        assert str(error) == error.message == "failed with status 500"


def test_a_transient_error_can_carry_a_retry_after_hint() -> None:
    assert LLMTransientError("busy", retry_after=2.5).retry_after == 2.5
    assert LLMTransientError("busy").retry_after is None


def test_the_wrapper_and_the_fake_satisfy_the_client_protocol() -> None:
    clients: list[LLMClient] = [StructuredLLM(ScriptedTransport([])), FakeLLMClient()]

    assert [client.provider for client in clients] == ["scripted", "fake"]
    assert [client.model for client in clients] == ["scripted-model", "fake-model"]
