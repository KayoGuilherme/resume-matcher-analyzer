"""The shared behavior around every provider call.

Everything provider-independent lives here so a new adapter cannot forget it: backoff on
transient errors, the native -> JSON-in-prompt fallback, optional sampling parameters, JSON
extraction, Pydantic validation, one repair attempt and content-free logging.
"""

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial

from pydantic import BaseModel

from app.ai.llm.base import (
    CompletionRequest,
    LLMError,
    LLMInvalidOutputError,
    LLMTransientError,
    StructuredOutputUnsupported,
    TokenUsage,
    Transport,
    UnsupportedParameter,
)
from app.ai.llm.output import OutputProblem, parse_structured
from app.core.retry import retry_async

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


@dataclass
class _CallStats:
    provider_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    saw_usage: bool = False
    fallback: bool = False
    repaired: bool = False
    extra: dict[str, object] = field(default_factory=dict)

    def add(self, usage: TokenUsage | None) -> None:
        self.provider_calls += 1
        if usage is not None:
            self.saw_usage = True
            self.input_tokens += usage.input_tokens or 0
            self.output_tokens += usage.output_tokens or 0


def _is_transient(error: Exception) -> bool:
    return isinstance(error, LLMTransientError)


def _retry_after(error: Exception) -> float | None:
    return error.retry_after if isinstance(error, LLMTransientError) else None


def _schema_instructions(schema: type[BaseModel]) -> str:
    return (
        "Respond with a single JSON object that conforms to this JSON schema, and nothing else "
        "(no Markdown, no commentary):\n" + json.dumps(schema.model_json_schema())
    )


def _repair_prompt(prompt: str, answer: str, problems: list[str]) -> str:
    return (
        f"{prompt}\n\nYour previous answer was:\n{answer}\n\n"
        "It is not valid for the requested schema:\n"
        + "\n".join(f"- {problem}" for problem in problems)
        + "\nAnswer again with the corrected JSON only."
    )


class StructuredLLM:
    """`LLMClient` over a `Transport`. One instance is kept per configuration, so what it learns
    about the provider (no native structured output, no temperature) is learned once."""

    def __init__(
        self,
        transport: Transport,
        *,
        temperature: float | None = 0.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,  # noqa: S311 - jitter, not security
    ) -> None:
        self._transport = transport
        self._temperature = temperature
        self._sleep = sleep
        self._rng = rng
        self._native_supported = True
        self._temperature_supported = True

    @property
    def transport(self) -> Transport:
        return self._transport

    @property
    def provider(self) -> str:
        return self._transport.provider

    @property
    def model(self) -> str:
        return self._transport.model

    async def generate_structured[T: BaseModel](
        self, prompt: str, schema: type[T], *, system: str | None = None
    ) -> T:
        stats = _CallStats()
        started = time.perf_counter()
        outcome = "success"
        try:
            answer = await self._complete(prompt, schema, system, stats)
            try:
                return parse_structured(answer, schema)
            except OutputProblem as problem:
                stats.repaired = True
                repaired = await self._complete(
                    _repair_prompt(prompt, answer, problem.problems), schema, system, stats
                )
                try:
                    return parse_structured(repaired, schema)
                except OutputProblem:
                    raise LLMInvalidOutputError(
                        "The model's answer did not match the requested schema, even after a "
                        "repair attempt"
                    ) from None
        except LLMError as error:
            outcome = type(error).__name__
            raise
        finally:
            if outcome == "success":
                outcome = (
                    "repaired" if stats.repaired else "fallback" if stats.fallback else outcome
                )
            self._log(outcome, stats, time.perf_counter() - started)

    async def _complete(
        self, prompt: str, schema: type[BaseModel], system: str | None, stats: _CallStats
    ) -> str:
        # Each `continue` clears a capability flag, so this loop runs at most three times.
        while True:
            native = self._native_supported
            temperature = self._temperature if self._temperature_supported else None
            request = CompletionRequest(
                prompt=prompt if native else f"{prompt}\n\n{_schema_instructions(schema)}",
                system=system,
                schema=schema,
                mode="native" if native else "prompt_json",
                temperature=temperature,
            )
            try:
                completion = await retry_async(
                    partial(self._transport.complete, request),
                    is_retryable=_is_transient,
                    attempts=MAX_ATTEMPTS,
                    delay_hint=_retry_after,
                    sleep=self._sleep,
                    rng=self._rng,
                )
            except StructuredOutputUnsupported:
                if not native:
                    raise LLMError("The provider rejected a request without a schema") from None
                self._native_supported = False
                stats.fallback = True
                continue
            except UnsupportedParameter as error:
                if temperature is None:
                    raise LLMError(
                        f"The provider rejected the {error.parameter} parameter"
                    ) from None
                self._temperature_supported = False
                continue
            stats.add(completion.usage)
            return completion.text

    def _log(self, outcome: str, stats: _CallStats, seconds: float) -> None:
        logger.log(
            logging.INFO if outcome in {"success", "repaired", "fallback"} else logging.WARNING,
            "llm call",
            extra={
                "llm_provider": self.provider,
                "llm_model": self.model,
                "outcome": outcome,
                "provider_calls": stats.provider_calls,
                "input_tokens": stats.input_tokens if stats.saw_usage else None,
                "output_tokens": stats.output_tokens if stats.saw_usage else None,
                "duration_ms": round(seconds * 1000),
            },
        )
