"""Build the configured LLM client. The one place that knows which provider is selected."""

from functools import lru_cache
from typing import Annotated

from anthropic import AsyncAnthropic
from fastapi import Depends
from openai import AsyncOpenAI

from app.ai.errors import AINotConfiguredError
from app.ai.llm.anthropic_client import AnthropicTransport
from app.ai.llm.base import LLMClient, Transport
from app.ai.llm.openai_client import OpenAITransport
from app.ai.llm.structured import StructuredLLM
from app.core.config import Settings, get_settings

# Local servers ignore the key but the SDK refuses to start without one.
_PLACEHOLDER_KEY = "not-needed"


def _require(settings: Settings) -> None:
    """Raise `AINotConfiguredError` naming the first missing setting (never a value)."""
    if settings.llm_provider is None:
        raise AINotConfiguredError(
            "No LLM is configured. Set LLM_PROVIDER to anthropic, openai or openai_compatible."
        )
    if not settings.llm_model:
        raise AINotConfiguredError("No LLM model is configured. Set LLM_MODEL.")
    if settings.llm_provider == "openai_compatible":
        if not settings.llm_base_url:
            raise AINotConfiguredError(
                "LLM_PROVIDER=openai_compatible needs LLM_BASE_URL, for example "
                "http://localhost:11434/v1."
            )
    elif settings.llm_api_key is None or not settings.llm_api_key.get_secret_value():
        raise AINotConfiguredError(
            f"LLM_PROVIDER={settings.llm_provider} needs LLM_API_KEY. Set it."
        )


def _build_transport(settings: Settings) -> Transport:
    model = settings.llm_model or ""
    key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    # max_retries=0: the shared wrapper owns the single retry policy.
    if settings.llm_provider == "anthropic":
        return AnthropicTransport(
            AsyncAnthropic(
                api_key=key,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout_seconds,
                max_retries=0,
            ),
            model,
        )
    return OpenAITransport(
        AsyncOpenAI(
            api_key=key or _PLACEHOLDER_KEY,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        ),
        model,
        provider="openai" if settings.llm_provider == "openai" else "openai_compatible",
    )


@lru_cache
def _client_for(settings: Settings) -> StructuredLLM:
    """One client per configuration, so what it learns about the provider is learned once."""
    return StructuredLLM(_build_transport(settings), temperature=settings.llm_temperature)


def get_llm_client(settings: Annotated[Settings, Depends(get_settings)]) -> LLMClient:
    """FastAPI dependency. Raises `AINotConfiguredError` (503) when no LLM is usable."""
    _require(settings)
    return _client_for(settings)
