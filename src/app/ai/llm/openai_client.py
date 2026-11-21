"""Adapter for the OpenAI Chat Completions API.

It also serves every OpenAI-compatible server (Ollama, LM Studio, vLLM, ...) through the SDK
client's `base_url`: Chat Completions is the one API all of them implement.
"""

from typing import Any, Literal

import openai
from openai import AsyncOpenAI, pydantic_function_tool
from openai.types.chat import ChatCompletionMessageParam

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


class OpenAITransport:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        *,
        provider: Literal["openai", "openai_compatible"] = "openai",
    ) -> None:
        self._client = client
        self._model = model
        self._provider = provider

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, request: CompletionRequest) -> RawCompletion:
        messages: list[ChatCompletionMessageParam] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.mode == "native":
            # The SDK helper makes the schema strict-compatible (all properties required,
            # additionalProperties false), which OpenAI's json_schema mode needs.
            tool = pydantic_function_tool(request.schema)
            options["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema.__name__,
                    "schema": tool["function"].get("parameters", {}),
                    "strict": True,
                },
            }
        try:
            completion = await self._client.chat.completions.create(
                model=self._model, messages=messages, **options
            )
        except openai.APITimeoutError:
            raise LLMTimeoutError("The provider did not answer in time") from None
        except openai.APIConnectionError:
            raise LLMTransientError("Could not connect to the provider") from None
        except openai.APIStatusError as error:
            raise _map_status_error(error, request) from None

        if not completion.choices:
            raise LLMInvalidOutputError("The provider returned no answer")
        choice = completion.choices[0]
        if choice.finish_reason == "length":
            raise LLMInvalidOutputError("The answer was cut off by the output length limit")
        content = choice.message.content
        if not content:
            raise LLMInvalidOutputError("The provider returned an empty answer")
        usage = None
        if completion.usage is not None:
            usage = TokenUsage(
                input_tokens=completion.usage.prompt_tokens,
                output_tokens=completion.usage.completion_tokens,
            )
        return RawCompletion(text=content, usage=usage)


def _map_status_error(error: openai.APIStatusError, request: CompletionRequest) -> Exception:
    status = error.status_code
    if status in {401, 403}:
        return LLMAuthError(f"The provider rejected the credentials (status {status})")
    if status == 429 or status >= 500:
        return LLMTransientError(
            f"The provider is unavailable (status {status})",
            retry_after=retry_after_seconds(error.response.headers),
        )
    if status in {400, 404, 422}:
        text = error_text(error.body)
        param = getattr(error, "param", None)
        if request.temperature is not None and mentions_temperature(param, text):
            return UnsupportedParameter("temperature")
        if request.mode == "native" and mentions_structured_output(param, text):
            return StructuredOutputUnsupported()
    return LLMError(f"The provider rejected the request (status {status})")
