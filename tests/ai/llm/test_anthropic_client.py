import httpx2
import pytest
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.ai.llm.anthropic_client import MAX_OUTPUT_TOKENS, AnthropicTransport
from app.ai.llm.base import (
    CompletionRequest,
    LLMAuthError,
    LLMError,
    LLMInvalidOutputError,
    LLMTimeoutError,
    LLMTransientError,
    Mode,
    StructuredOutputUnsupported,
    UnsupportedParameter,
)
from tests.ai.llm.http import Recorder, json_response, mock_http_client

KEY = "sk-ant-test-key-123"


class Person(BaseModel):
    name: str
    age: int | None = None


def _message(content: list[dict[str, object]], stop_reason: str = "end_turn") -> dict[str, object]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "m",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 21, "output_tokens": 8},
    }


def _tool_use(data: dict[str, object]) -> dict[str, object]:
    return _message([{"type": "tool_use", "id": "t1", "name": "Person", "input": data}], "tool_use")


def _transport(recorder: Recorder) -> AnthropicTransport:
    client = AsyncAnthropic(api_key=KEY, max_retries=0, http_client=mock_http_client(recorder))
    return AnthropicTransport(client, "the-model")


def _request(
    mode: Mode = "native", temperature: float | None = 0.0, system: str | None = "Be brief"
) -> CompletionRequest:
    return CompletionRequest(
        prompt="PROMPT-WITH-RESUME-TEXT",
        system=system,
        schema=Person,
        mode=mode,
        temperature=temperature,
    )


async def test_native_mode_forces_one_tool_and_returns_its_input() -> None:
    recorder = Recorder(json_response(_tool_use({"name": "Ana", "age": 30})))

    result = await _transport(recorder).complete(_request())

    body = recorder.body
    assert body["model"] == "the-model"
    assert body["max_tokens"] == MAX_OUTPUT_TOKENS
    assert body["temperature"] == 0.0
    assert body["system"] == "Be brief"
    assert body["messages"] == [{"role": "user", "content": "PROMPT-WITH-RESUME-TEXT"}]
    (tool,) = body["tools"]
    assert tool["name"] == "Person"
    assert tool["input_schema"]["properties"]["name"]["type"] == "string"
    assert body["tool_choice"] == {"type": "tool", "name": "Person"}
    assert KEY in recorder.requests[0].headers["authorization"]
    assert result.text == '{"name": "Ana", "age": 30}'
    assert (result.usage.input_tokens, result.usage.output_tokens) == (21, 8)  # type: ignore[union-attr]


async def test_prompt_json_mode_returns_the_text_and_sends_no_tools() -> None:
    recorder = Recorder(json_response(_message([{"type": "text", "text": '{"name": "Ana"}'}])))

    result = await _transport(recorder).complete(_request("prompt_json", None, None))

    body = recorder.body
    assert "tools" not in body and "tool_choice" not in body
    assert "temperature" not in body and "system" not in body
    assert result.text == '{"name": "Ana"}'


@pytest.mark.parametrize(
    "payload",
    [
        _message([]),
        _message([{"type": "text", "text": "no tool call"}]),
        _tool_use({"name": "Ana"}) | {"stop_reason": "max_tokens"},
    ],
)
async def test_unusable_answers_are_invalid_output(payload: object) -> None:
    with pytest.raises(LLMInvalidOutputError):
        await _transport(Recorder(json_response(payload))).complete(_request())


@pytest.mark.parametrize("status", [401, 403])
async def test_credential_failures_are_auth_errors(status: int) -> None:
    body = {"type": "error", "error": {"type": "authentication_error", "message": f"bad {KEY}"}}

    with pytest.raises(LLMAuthError) as exc_info:
        await _transport(Recorder(json_response(body, status))).complete(_request())

    assert KEY not in str(exc_info.value)
    assert "PROMPT-WITH-RESUME-TEXT" not in str(exc_info.value)


@pytest.mark.parametrize("status", [429, 500, 529])
async def test_rate_limits_and_overload_are_transient(status: int) -> None:
    body = {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}

    with pytest.raises(LLMTransientError):
        await _transport(Recorder(json_response(body, status))).complete(_request())


async def test_retry_after_is_passed_on() -> None:
    body = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}}
    recorder = Recorder(json_response(body, 429, {"retry-after": "4"}))

    with pytest.raises(LLMTransientError) as exc_info:
        await _transport(recorder).complete(_request())

    assert exc_info.value.retry_after == 4.0


async def test_connection_problems_are_transient_and_timeouts_are_timeouts() -> None:
    with pytest.raises(LLMTransientError):
        await _transport(Recorder(httpx2.ConnectError("refused"))).complete(_request())
    with pytest.raises(LLMTimeoutError):
        await _transport(Recorder(httpx2.ReadTimeout("slow"))).complete(_request())


async def test_a_temperature_rejection_is_an_unsupported_parameter() -> None:
    body = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "`temperature` is deprecated for this model.",
        },
    }

    with pytest.raises(UnsupportedParameter):
        await _transport(Recorder(json_response(body, 400))).complete(_request())


async def test_a_tool_use_rejection_is_recognized_in_native_mode_only() -> None:
    body = {
        "type": "error",
        "error": {"type": "invalid_request_error", "message": "tool_choice is not supported"},
    }

    with pytest.raises(StructuredOutputUnsupported):
        await _transport(Recorder(json_response(body, 400))).complete(_request())
    with pytest.raises(LLMError) as exc_info:
        await _transport(Recorder(json_response(body, 400))).complete(_request("prompt_json"))
    assert not isinstance(exc_info.value, StructuredOutputUnsupported)


async def test_other_rejections_are_a_general_error_with_only_the_status() -> None:
    body = {"type": "error", "error": {"type": "not_found_error", "message": "model: nope"}}

    with pytest.raises(LLMError) as exc_info:
        await _transport(Recorder(json_response(body, 404))).complete(_request())

    assert str(exc_info.value) == "The provider rejected the request (status 404)"
