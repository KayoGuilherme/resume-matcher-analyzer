"""Adapter for the Anthropic Messages API (native structured output through a forced tool)."""

import json
from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from app.ai.llm._errors import (
    error_text,
    mentions_structured_output,
    mentions_temperature,
)
from app.ai.llm.base import (
    CompletionRequest,
    LLMAuthError,
    LLMError,
    LLMInvalidOutputError,
    LLMTimeoutError,
    LLMTransientError,
    RawCompletion,
    StructuredOutputUnsupported,
    TokenUsage,
    UnsupportedParameter,
)
from app.core.retry import retry_after_seconds

# Anthropic requires an output limit. Large enough for a long resume's extraction.
MAX_OUTPUT_TOKENS = 8192


class AnthropicTransport:
    def __init__(self, client: AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def provider(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, request: CompletionRequest) -> RawCompletion:
        options: dict[str, Any] = {}
        if request.system:
            options["system"] = request.system
        if request.temperature is not None:
            # Current SDK versions dropped the typed parameter because newer models reject
            # sampling parameters; older ones still accept it. A rejection is learned once by
            # the shared wrapper, so the body field is the way to honor LLM_TEMPERATURE.
            options["extra_body"] = {"temperature": request.temperature}
        tool_name = request.schema.__name__
        if request.mode == "native":
            options["tools"] = [
                {
                    "name": tool_name,
                    "description": "Return the requested data by calling this tool once.",
                    "input_schema": request.schema.model_json_schema(),
                }
            ]
            options["tool_choice"] = {"type": "tool", "name": tool_name}
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=MAX_OUTPUT_TOKENS,
                messages=[{"role": "user", "content": request.prompt}],
                **options,
            )
        except anthropic.APITimeoutError:
            raise LLMTimeoutError("The provider did not answer in time") from None
        except anthropic.APIConnectionError:
            raise LLMTransientError("Could not connect to the provider") from None
        except anthropic.APIStatusError as error:
            raise _map_status_error(error, request) from None

        if message.stop_reason == "max_tokens":
            raise LLMInvalidOutputError("The answer was cut off by the output length limit")
        text: str | None = None
        for block in message.content:
            if request.mode == "native" and block.type == "tool_use":
                text = json.dumps(block.input)
                break
            if request.mode == "prompt_json" and block.type == "text":
                text = (text or "") + block.text
        if not text:
            raise LLMInvalidOutputError("The provider returned no answer")
        return RawCompletion(
            text=text,
            usage=TokenUsage(
                input_tokens=message.usage.input_tokens, output_tokens=message.usage.output_tokens
            ),
        )


def _map_status_error(error: anthropic.APIStatusError, request: CompletionRequest) -> Exception:
    status = error.status_code
    if status in {401, 403}:
        return LLMAuthError(f"The provider rejected the credentials (status {status})")
    if status == 429 or status >= 500:  # 529 is "overloaded"
        return LLMTransientError(
            f"The provider is unavailable (status {status})",
            retry_after=retry_after_seconds(error.response.headers),
        )
    if status in {400, 404, 422}:
        text = error_text(error.body)
        if request.temperature is not None and mentions_temperature(None, text):
            return UnsupportedParameter("temperature")
        if request.mode == "native" and mentions_structured_output(None, text):
            return StructuredOutputUnsupported()
    return LLMError(f"The provider rejected the request (status {status})")
