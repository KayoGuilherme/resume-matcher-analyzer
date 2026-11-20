import logging

import pytest
from pydantic import BaseModel

from app.ai.llm.base import (
    LLMAuthError,
    LLMError,
    LLMInvalidOutputError,
    LLMTimeoutError,
    LLMTransientError,
    StructuredOutputUnsupported,
    TokenUsage,
    UnsupportedParameter,
)
from app.ai.llm.structured import MAX_ATTEMPTS, StructuredLLM
from tests.ai.llm.transport import ScriptedTransport

VALID = '{"name": "Ana", "age": 30}'
INVALID = '{"name": "Ana"}'


class Person(BaseModel):
    name: str
    age: int


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def _client(
    script: list[str | Exception],
    *,
    temperature: float | None = 0.0,
    usage: TokenUsage | None = None,
    sleeps: Sleeps | None = None,
) -> tuple[StructuredLLM, ScriptedTransport]:
    transport = ScriptedTransport(script, usage)
    client = StructuredLLM(
        transport, temperature=temperature, sleep=sleeps or Sleeps(), rng=lambda: 1.0
    )
    return client, transport


async def test_a_valid_answer_returns_an_instance_with_one_provider_call() -> None:
    client, transport = _client([VALID])

    result = await client.generate_structured("Who?", Person, system="Be brief")

    assert result == Person(name="Ana", age=30)
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert (request.prompt, request.system, request.mode) == ("Who?", "Be brief", "native")
    assert request.schema is Person


async def test_json_wrapped_in_a_code_fence_is_accepted() -> None:
    client, _ = _client([f"```json\n{VALID}\n```"])

    assert await client.generate_structured("Who?", Person) == Person(name="Ana", age=30)


async def test_the_repair_attempt_fixes_an_invalid_answer() -> None:
    client, transport = _client([INVALID, VALID])

    result = await client.generate_structured("Who?", Person)

    assert result.age == 30
    assert len(transport.requests) == 2
    repair = transport.requests[1].prompt
    assert repair.startswith("Who?")
    assert INVALID in repair
    assert "age:" in repair


async def test_a_failed_repair_raises_invalid_output_after_exactly_two_calls() -> None:
    client, transport = _client([INVALID, "still not json"])

    with pytest.raises(LLMInvalidOutputError):
        await client.generate_structured("Who?", Person)

    assert len(transport.requests) == 2


async def test_native_rejection_falls_back_to_json_in_the_prompt() -> None:
    client, transport = _client([StructuredOutputUnsupported(), VALID])

    result = await client.generate_structured("Who?", Person)

    assert result.name == "Ana"
    native, fallback = transport.requests
    assert native.mode == "native"
    assert fallback.mode == "prompt_json"
    assert fallback.prompt.startswith("Who?")
    assert '"properties"' in fallback.prompt


async def test_the_fallback_is_remembered_for_later_calls() -> None:
    client, transport = _client([StructuredOutputUnsupported(), VALID, VALID])

    await client.generate_structured("one", Person)
    await client.generate_structured("two", Person)

    assert [r.mode for r in transport.requests] == ["native", "prompt_json", "prompt_json"]


async def test_the_repair_attempt_keeps_the_learned_mode() -> None:
    client, transport = _client([StructuredOutputUnsupported(), INVALID, VALID])

    await client.generate_structured("Who?", Person)

    assert [r.mode for r in transport.requests] == ["native", "prompt_json", "prompt_json"]


async def test_rejecting_the_schema_in_prompt_mode_is_an_error() -> None:
    client, _ = _client([StructuredOutputUnsupported(), StructuredOutputUnsupported()])

    with pytest.raises(LLMError):
        await client.generate_structured("Who?", Person)


async def test_the_default_temperature_is_zero() -> None:
    client, transport = _client([VALID])

    await client.generate_structured("Who?", Person)

    assert transport.requests[0].temperature == 0.0


async def test_a_rejected_temperature_is_dropped_and_remembered() -> None:
    client, transport = _client([UnsupportedParameter("temperature"), VALID, VALID])

    await client.generate_structured("one", Person)
    await client.generate_structured("two", Person)

    assert [r.temperature for r in transport.requests] == [0.0, None, None]


async def test_a_disabled_temperature_is_never_sent() -> None:
    client, transport = _client([VALID], temperature=None)

    await client.generate_structured("Who?", Person)

    assert transport.requests[0].temperature is None


async def test_temperature_rejected_without_one_sent_is_an_error() -> None:
    client, _ = _client([UnsupportedParameter("temperature")], temperature=None)

    with pytest.raises(LLMError, match="temperature"):
        await client.generate_structured("Who?", Person)


async def test_a_transient_error_is_retried_after_a_backoff_wait() -> None:
    sleeps = Sleeps()
    client, transport = _client([LLMTransientError("status 503"), VALID], sleeps=sleeps)

    result = await client.generate_structured("Who?", Person)

    assert result.name == "Ana"
    assert len(transport.requests) == 2
    assert sleeps.delays == [1.0]


async def test_a_retry_after_hint_sets_the_wait() -> None:
    sleeps = Sleeps()
    client, _ = _client([LLMTransientError("status 429", retry_after=3.0), VALID], sleeps=sleeps)

    await client.generate_structured("Who?", Person)

    assert sleeps.delays == [3.0]


async def test_exhausted_transient_errors_are_raised_after_the_maximum_attempts() -> None:
    sleeps = Sleeps()
    client, transport = _client([LLMTransientError("status 429")] * 5, sleeps=sleeps)

    with pytest.raises(LLMTransientError):
        await client.generate_structured("Who?", Person)

    assert len(transport.requests) == MAX_ATTEMPTS == 3
    assert len(sleeps.delays) == 2


@pytest.mark.parametrize("error", [LLMAuthError("status 401"), LLMTimeoutError("timed out")])
async def test_auth_failures_and_timeouts_are_not_retried(error: LLMError) -> None:
    sleeps = Sleeps()
    client, transport = _client([error, VALID], sleeps=sleeps)

    with pytest.raises(type(error)):
        await client.generate_structured("Who?", Person)

    assert len(transport.requests) == 1
    assert sleeps.delays == []


async def test_each_call_logs_provider_model_tokens_and_duration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = _client([VALID], usage=TokenUsage(input_tokens=11, output_tokens=7))

    with caplog.at_level(logging.INFO, logger="app.ai.llm.structured"):
        await client.generate_structured("Who?", Person)

    (record,) = caplog.records
    assert record.__dict__["llm_provider"] == "scripted"
    assert record.__dict__["llm_model"] == "scripted-model"
    assert record.__dict__["input_tokens"] == 11
    assert record.__dict__["output_tokens"] == 7
    assert record.__dict__["outcome"] == "success"
    assert record.__dict__["duration_ms"] >= 0


async def test_the_outcome_names_repair_fallback_and_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="app.ai.llm.structured"):
        repaired, _ = _client([INVALID, VALID])
        await repaired.generate_structured("Who?", Person)
        fallback, _ = _client([StructuredOutputUnsupported(), VALID])
        await fallback.generate_structured("Who?", Person)
        failing, _ = _client([LLMAuthError("status 401")])
        with pytest.raises(LLMAuthError):
            await failing.generate_structured("Who?", Person)

    assert [r.__dict__["outcome"] for r in caplog.records] == [
        "repaired",
        "fallback",
        "LLMAuthError",
    ]


async def test_logs_never_contain_the_prompt_or_the_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = _client([INVALID, VALID], usage=TokenUsage(input_tokens=1, output_tokens=1))

    with caplog.at_level(logging.DEBUG):
        await client.generate_structured("Tell me about SECRET-RESUME-TEXT", Person)

    logged = " ".join(str(record.__dict__) + record.getMessage() for record in caplog.records)
    assert "SECRET-RESUME-TEXT" not in logged
    assert "Ana" not in logged
