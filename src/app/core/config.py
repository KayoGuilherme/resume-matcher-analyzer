"""Application settings. Read only from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
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

    # Gap analysis. The similarity floor depends on the embedding model: tune it with the evals.
    analysis_top_k: int = Field(default=5, ge=1, le=20)
    analysis_min_similarity: float = Field(default=0.4, ge=0, le=1, allow_inf_nan=False)
    analysis_max_requirements_per_call: int = Field(default=8, ge=1, le=50)
    analysis_max_llm_calls: int = Field(default=10, ge=1, le=100)

    # Score, screener and report. The weights are relative (scaled to add up to one); the
    # penalties and thresholds are on the score's 0-100 scale. Tune them with the evals.
    score_weight_must_have: float = Field(default=0.6, ge=0, le=1, allow_inf_nan=False)
    score_weight_nice_to_have: float = Field(default=0.15, ge=0, le=1, allow_inf_nan=False)
    score_weight_keywords: float = Field(default=0.25, ge=0, le=1, allow_inf_nan=False)
    score_partial_credit: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    score_penalty_critical: float = Field(default=40, ge=0, le=100, allow_inf_nan=False)
    score_penalty_warning: float = Field(default=5, ge=0, le=100, allow_inf_nan=False)
    score_penalty_info: float = Field(default=1, ge=0, le=100, allow_inf_nan=False)
    score_pass_threshold: float = Field(default=70, ge=0, le=100, allow_inf_nan=False)
    score_borderline_threshold: float = Field(default=50, ge=0, le=100, allow_inf_nan=False)
    screener_runs: int = Field(default=3, ge=1, le=10)
    report_max_suggestions: int = Field(default=8, ge=0, le=30)

    @model_validator(mode="after")
    def _score_settings_are_consistent(self) -> Self:
        if not (
            self.score_weight_must_have
            or self.score_weight_nice_to_have
            or self.score_weight_keywords
        ):
            raise ValueError(
                "SCORE_WEIGHT_MUST_HAVE, SCORE_WEIGHT_NICE_TO_HAVE and SCORE_WEIGHT_KEYWORDS "
                "cannot all be 0"
            )
        if self.score_borderline_threshold >= self.score_pass_threshold:
            raise ValueError("SCORE_BORDERLINE_THRESHOLD must be lower than SCORE_PASS_THRESHOLD")
        return self

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
