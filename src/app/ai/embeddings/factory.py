"""Build the configured embeddings client. The one place that knows which provider is selected."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from openai import AsyncOpenAI

from app.ai.embeddings.base import BatchingEmbeddingClient, EmbeddingClient, EmbeddingTransport
from app.ai.embeddings.local import LocalEmbeddingTransport
from app.ai.embeddings.openai_client import OpenAIEmbeddingTransport
from app.ai.errors import AINotConfiguredError
from app.core.config import Settings, get_settings

DEFAULT_COMPATIBLE_BASE_URL = "http://localhost:11434/v1"  # Ollama
_PLACEHOLDER_KEY = "not-needed"  # local servers ignore the key; the SDK needs one
_TIMEOUT_SECONDS = 120.0


def _require(settings: Settings) -> None:
    if settings.embedding_provider == "openai" and (
        settings.embedding_api_key is None or not settings.embedding_api_key.get_secret_value()
    ):
        raise AINotConfiguredError("EMBEDDING_PROVIDER=openai needs EMBEDDING_API_KEY. Set it.")


def _build_transport(settings: Settings) -> EmbeddingTransport:
    if settings.embedding_provider == "local":
        return LocalEmbeddingTransport(settings.embedding_model)
    key = settings.embedding_api_key.get_secret_value() if settings.embedding_api_key else ""
    hosted = settings.embedding_provider == "openai"
    base_url = settings.embedding_base_url or (None if hosted else DEFAULT_COMPATIBLE_BASE_URL)
    # `dimensions` lets hosted text-embedding-3* models be cut to the column size.
    dimensions = (
        settings.embedding_dimension
        if hosted and settings.embedding_model.startswith("text-embedding-3")
        else None
    )
    return OpenAIEmbeddingTransport(
        AsyncOpenAI(
            api_key=key or _PLACEHOLDER_KEY,
            base_url=base_url,
            timeout=_TIMEOUT_SECONDS,
            max_retries=0,
        ),
        settings.embedding_model,
        provider="openai" if hosted else "openai_compatible",
        dimensions=dimensions,
    )


@lru_cache
def _client_for(settings: Settings) -> BatchingEmbeddingClient:
    """One client per configuration (a local model is loaded once, on first use)."""
    return BatchingEmbeddingClient(
        _build_transport(settings), dimension=settings.embedding_dimension
    )


def get_embedding_client(settings: Annotated[Settings, Depends(get_settings)]) -> EmbeddingClient:
    """FastAPI dependency. Raises `AINotConfiguredError` (503) when embeddings are not usable."""
    _require(settings)
    return _client_for(settings)
