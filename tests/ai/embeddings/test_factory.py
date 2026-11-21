from typing import Any

import pytest

from app.ai.embeddings import get_embedding_client
from app.ai.embeddings.base import BatchingEmbeddingClient
from app.ai.embeddings.factory import DEFAULT_COMPATIBLE_BASE_URL
from app.ai.embeddings.local import LocalEmbeddingTransport
from app.ai.embeddings.openai_client import OpenAIEmbeddingTransport
from app.ai.errors import AINotConfiguredError
from app.core.config import Settings

DB = "postgresql+asyncpg://u:p@localhost:5432/x"


def _settings(**values: Any) -> Settings:
    return Settings(database_url=DB, **values)


def _built(**values: Any) -> BatchingEmbeddingClient:
    client = get_embedding_client(_settings(**values))
    assert isinstance(client, BatchingEmbeddingClient)
    return client


def test_defaults_give_a_compatible_client_for_bge_m3_at_1024_dimensions() -> None:
    client = _built()

    assert isinstance(client.transport, OpenAIEmbeddingTransport)
    assert client.provider == "openai_compatible"
    assert (client.model_name, client.dimension) == ("bge-m3", 1024)
    assert DEFAULT_COMPATIBLE_BASE_URL == "http://localhost:11434/v1"


def test_the_hosted_provider_needs_a_key_and_reduces_text_embedding_3_models() -> None:
    client = _built(
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_api_key="k",
    )

    assert client.provider == "openai"
    assert client.transport._dimensions == 1024  # type: ignore[attr-defined]


def test_other_hosted_models_do_not_get_a_dimensions_parameter() -> None:
    client = _built(
        embedding_provider="openai", embedding_model="text-embedding-ada-002", embedding_api_key="k"
    )

    assert client.transport._dimensions is None  # type: ignore[attr-defined]


def test_the_compatible_provider_never_sends_dimensions() -> None:
    client = _built(embedding_model="text-embedding-3-small")

    assert client.transport._dimensions is None  # type: ignore[attr-defined]


def test_the_local_provider_needs_no_key() -> None:
    client = _built(embedding_provider="local", embedding_model="BAAI/bge-m3")

    assert isinstance(client.transport, LocalEmbeddingTransport)
    assert client.provider == "local"


def test_the_hosted_provider_without_a_key_names_the_setting() -> None:
    with pytest.raises(AINotConfiguredError) as exc_info:
        get_embedding_client(_settings(embedding_provider="openai"))
    with pytest.raises(AINotConfiguredError):
        get_embedding_client(_settings(embedding_provider="openai", embedding_api_key=""))

    assert "EMBEDDING_API_KEY" in exc_info.value.message
    assert exc_info.value.code == "ai_not_configured"


def test_the_client_is_cached_per_settings() -> None:
    settings = _settings(embedding_provider="local")

    assert get_embedding_client(settings) is get_embedding_client(settings)
    assert get_embedding_client(settings) is not get_embedding_client(
        _settings(embedding_provider="local", embedding_model="other")
    )


def test_the_embedding_configuration_is_independent_from_the_llm() -> None:
    client = _built(llm_provider="anthropic", llm_model="m", llm_api_key="k")

    assert client.provider == "openai_compatible"
