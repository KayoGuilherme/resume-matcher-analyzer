"""Fixtures for tests that call the provider configured in the environment.

Run them with `uv run --env-file .env pytest -m real_provider`. They are excluded from the default
run and from CI, and skipped (with the reason) when nothing usable is configured.
"""

import os

import pytest

from app.ai.embeddings import EmbeddingClient, get_embedding_client
from app.ai.errors import AINotConfiguredError
from app.ai.llm import LLMClient, get_llm_client
from app.core.config import Settings

EMBEDDING_VARIABLES = (
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_API_KEY",
    "EMBEDDING_BASE_URL",
)


@pytest.fixture(scope="session")
def real_settings() -> Settings:
    # The database is not used here; Settings only needs a value for it.
    database_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://unused@localhost/unused")
    return Settings(database_url=database_url)


@pytest.fixture
def real_llm(real_settings: Settings) -> LLMClient:
    try:
        return get_llm_client(real_settings)
    except AINotConfiguredError as error:
        pytest.skip(f"no LLM configured: {error.message}")


@pytest.fixture
def real_embedder(real_settings: Settings) -> EmbeddingClient:
    if not any(os.environ.get(name) for name in EMBEDDING_VARIABLES):
        pytest.skip("no embeddings configured: none of the EMBEDDING_* variables is set")
    try:
        return get_embedding_client(real_settings)
    except AINotConfiguredError as error:
        pytest.skip(f"embeddings not usable: {error.message}")
