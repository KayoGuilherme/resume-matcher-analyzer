"""The provider-independent LLM interface, its typed errors and the transport adapters implement.

Business code depends on `LLMClient` only. Adapters implement the small `Transport` protocol;
`StructuredLLM` (structured.py) adds validation, repair, fallback, retries and logging on top.
Error messages are built from status codes and error types, never from request or answer content.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict


class LLMError(Exception):
    """Base class for every failure of the LLM layer. No provider exception escapes it."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LLMTransientError(LLMError):
    """Rate limit, server error or connection problem. Worth retrying."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMInvalidOutputError(LLMError):
    """The answer could not be turned into the requested schema, even after a repair attempt."""


class LLMAuthError(LLMError):
    """Missing, wrong or forbidden credentials."""


class LLMTimeoutError(LLMError):
    """No answer within the configured timeout."""


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int | None = None
    output_tokens: int | None = None


Mode = Literal["native", "prompt_json"]


@dataclass(frozen=True)
class CompletionRequest:
    """One call to a provider. In `prompt_json` mode the prompt already describes the schema."""

    prompt: str
    system: str | None
    schema: type[BaseModel]
    mode: Mode
    temperature: float | None


@dataclass(frozen=True)
class RawCompletion:
    """The answer as JSON-ish text (native tool input is serialized) plus the usage reported."""

    text: str
    usage: TokenUsage | None = None


class StructuredOutputUnsupported(Exception):
    """The provider or model rejected the native structured-output mechanism."""


class UnsupportedParameter(Exception):
    """The provider or model rejected a sampling parameter (for example `temperature`)."""

    def __init__(self, parameter: str) -> None:
        super().__init__(parameter)
        self.parameter = parameter


class Transport(Protocol):
    """What an adapter implements: one provider call, typed errors, nothing else."""

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def complete(self, request: CompletionRequest) -> RawCompletion:
        """Raise `LLMTransientError`, `LLMAuthError`, `LLMTimeoutError`, `LLMError`,
        `StructuredOutputUnsupported` or `UnsupportedParameter`; never an SDK exception."""
        ...


class LLMClient(Protocol):
    """Ask a model for structured data. The result is always a validated `schema` instance."""

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def generate_structured[T: BaseModel](
        self, prompt: str, schema: type[T], *, system: str | None = None
    ) -> T: ...
