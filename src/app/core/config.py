"""Application settings. Read only from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration (no .env file is read by the code)."""

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    database_url: str
    app_env: str = "local"
    log_level: str = "INFO"
    resume_max_upload_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    resume_storage_dir: Path = Path("data/resumes")

    # LLM. No provider by default: the app runs without one and only the endpoints that need an
    # LLM answer 503 `ai_not_configured` (cross-field checks live in the factory, not here).
    llm_provider: Literal["anthropic", "openai", "openai_compatible"] | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_timeout_seconds: float = Field(default=120, gt=0)
    llm_temperature: float | None = Field(default=0, ge=0, le=2)  # empty: never send one

    # Embeddings, independent from the LLM. The default is a local OpenAI-compatible server
    # (Ollama, http://localhost:11434/v1 when no base URL is set) serving the multilingual
    # `bge-m3`. 2000 is pgvector's limit for HNSW indexes.
    embedding_provider: Literal["local", "openai", "openai_compatible"] = "openai_compatible"
    embedding_model: str = "bge-m3"
    embedding_dimension: int = Field(default=1024, ge=1, le=2000)
    embedding_api_key: SecretStr | None = None
    embedding_base_url: str | None = None  # openai_compatible then uses the local Ollama address

    @field_validator(
        "llm_provider",
        "llm_model",
        "llm_api_key",
        "llm_base_url",
        "llm_temperature",
        "embedding_api_key",
        "embedding_base_url",
        mode="before",
    )
    @classmethod
    def _empty_means_unset(cls, value: Any) -> Any:
        """`NAME=` in an env file means "not set", not an invalid empty value."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings. Use as a FastAPI dependency."""
    return Settings()  # type: ignore[call-arg]
