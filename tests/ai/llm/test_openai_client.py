import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

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
from app.ai.llm.openai_client import OpenAITransport
from tests.ai.llm.http import Recorder, json_response, mock_http_client

KEY = "sk-test-key-123"


class Person(BaseModel):
    name: str
    age: int | None


def _completion(content: str | None = '{"name": "Ana", "age": 30}', **extra: object) -> object:
    payload = {
        "id": "c1",
        "object": "chat.completion",
        "created": 1,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": extra.pop("finish_reason", "stop"),
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
    }
    payload.update(extra)
    return payload


def _transport(
    recorder: Recorder, *, base_url: str | None = None, provider: str = "openai"
) -> OpenAITransport:
    client = AsyncOpenAI(
        api_key=KEY,
        base_url=base_url,
        max_retries=0,
        http_client=mock_http_client(recorder),
    )
    return OpenAITransport(client, "the-model", provider=provider)  # type: ignore[arg-type]


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


async def test_native_request_uses_a_strict_json_schema_response_format() -> None:
    recorder = Recorder(json_response(_completion()))

    result = await _transport(recorder).complete(_request())

    body = recorder.body
    assert body["model"] == "the-model"
    assert body["temperature"] == 0.0
    assert body["messages"] == [
        {"role": "system", "content": "Be brief"},
        {"role": "user", "content": "PROMPT-WITH-RESUME-TEXT"},
    ]
    response_format = body["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "Person"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == ["age", "name"]
    assert recorder.requests[0].headers["authorization"] == f"Bearer {KEY}"
    assert result.text == '{"name": "Ana", "age": 30}'
    assert (result.usage.input_tokens, result.usage.output_tokens) == (12, 5)  # type: ignore[union-attr]


async def test_prompt_json_mode_sends_no_schema_and_no_system_when_none() -> None:
    recorder = Recorder(json_response(_completion()))

    await _transport(recorder).complete(_request("prompt_json", temperature=None, system=None))

    body = recorder.body
    assert "response_format" not in body
    assert "temperature" not in body
    assert [m["role"] for m in body["messages"]] == ["user"]


async def test_a_custom_base_url_is_used() -> None:
    recorder = Recorder(json_response(_completion()))

    transport = _transport(
        recorder, base_url="http://localhost:11434/v1", provider="openai_compatible"
    )
    await transport.complete(_request())

    assert str(recorder.requests[0].url) == "http://localhost:11434/v1/chat/completions"
    assert transport.provider == "openai_compatible"
    assert transport.model == "the-model"


async def test_missing_usage_is_tolerated() -> None:
    payload = _completion()
    assert isinstance(payload, dict)
    del payload["usage"]

    result = await _transport(Recorder(json_response(payload))).complete(_request())

    assert result.usage is None


@pytest.mark.parametrize(
    "payload",
    [
        {**_completion(), "choices": []},
        _completion(content=""),
        _completion(content=None),
        _completion(finish_reason="length"),
    ],
)
async def test_unusable_answers_are_invalid_output(payload: object) -> None:
    with pytest.raises(LLMInvalidOutputError):
        await _transport(Recorder(json_response(payload))).complete(_request())


@pytest.mark.parametrize(("status", "error"), [(401, LLMAuthError), (403, LLMAuthError)])
async def test_credential_failures_are_auth_errors(status: int, error: type[LLMError]) -> None:
    recorder = Recorder(json_response({"error": {"message": f"bad key {KEY}"}}, status))

    with pytest.raises(error) as exc_info:
        await _transport(recorder).complete(_request())

    assert KEY not in str(exc_info.value)
    assert "PROMPT-WITH-RESUME-TEXT" not in str(exc_info.value)
    assert f"status {status}" in str(exc_info.value)


@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_rate_limits_and_server_errors_are_transient(status: int) -> None:
    recorder = Recorder(json_response({"error": {"message": "busy"}}, status))

    with pytest.raises(LLMTransientError):
        await _transport(recorder).complete(_request())


async def test_retry_after_is_passed_on() -> None:
    recorder = Recorder(json_response({"error": {"message": "slow"}}, 429, {"retry-after": "7"}))

    with pytest.raises(LLMTransientError) as exc_info:
        await _transport(recorder).complete(_request())

    assert exc_info.value.retry_after == 7.0


async def test_connection_problems_are_transient() -> None:
    recorder = Recorder(httpx2.ConnectError("refused"))

    with pytest.raises(LLMTransientError):
        await _transport(recorder).complete(_request())


async def test_a_timeout_is_a_timeout_error() -> None:
    recorder = Recorder(httpx2.ReadTimeout("too slow"))

    with pytest.raises(LLMTimeoutError):
        await _transport(recorder).complete(_request())


async def test_an_openai_temperature_rejection_is_an_unsupported_parameter() -> None:
    body = {
        "error": {
            "message": "Unsupported value: 'temperature' does not support 0 with this model.",
            "type": "invalid_request_error",
            "param": "temperature",
            "code": "unsupported_value",
        }
    }

    with pytest.raises(UnsupportedParameter) as exc_info:
        await _transport(Recorder(json_response(body, 400))).complete(_request())

    assert exc_info.value.parameter == "temperature"


async def test_a_temperature_error_is_not_reported_when_none_was_sent() -> None:
    body = {"error": {"message": "temperature is odd", "param": "temperature"}}

    with pytest.raises(LLMError) as exc_info:
        await _transport(Recorder(json_response(body, 400))).complete(_request(temperature=None))

    assert not isinstance(exc_info.value, LLMAuthError | LLMTransientError)


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"message": "Invalid parameter", "param": "response_format", "code": "x"}},
        {"object": "error", "message": "json_schema response_format is not supported", "code": 400},
        {"error": "registry.ollama.ai/library/llama2 does not support tools"},
    ],
)
async def test_servers_that_reject_the_native_mechanism_are_recognized(body: object) -> None:
    with pytest.raises(StructuredOutputUnsupported):
        await _transport(Recorder(json_response(body, 400))).complete(_request())


async def test_the_same_rejection_in_prompt_mode_is_a_plain_error() -> None:
    body = {"error": {"message": "response_format nope", "param": "response_format"}}

    with pytest.raises(LLMError) as exc_info:
        await _transport(Recorder(json_response(body, 400))).complete(_request("prompt_json"))

    assert not isinstance(exc_info.value, StructuredOutputUnsupported)


async def test_an_unknown_model_is_a_general_llm_error_with_only_the_status() -> None:
    body = {"error": {"message": "The model `the-model` does not exist", "code": "model_not_found"}}

    with pytest.raises(LLMError) as exc_info:
        await _transport(Recorder(json_response(body, 404))).complete(_request())

    assert type(exc_info.value) is LLMError
    assert str(exc_info.value) == "The provider rejected the request (status 404)"


def test_the_production_schema_classes_have_strict_compatible_schemas() -> None:
    from openai import pydantic_function_tool

    from app.ai.extraction.job_models import ExtractedJob
    from app.ai.extraction.models import ExtractedResume
    from app.ai.matching.models import JudgeBatch
    from app.ai.matching.report_models import ScreenerAnswer, SuggestionBatch

    for schema in (
        Person,
        ExtractedResume,
        ExtractedJob,
        JudgeBatch,
        ScreenerAnswer,
        SuggestionBatch,
    ):
        parameters = pydantic_function_tool(schema)["function"].get("parameters", {})
        assert parameters["additionalProperties"] is False
