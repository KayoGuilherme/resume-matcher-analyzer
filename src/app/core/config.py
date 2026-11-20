"""Application settings. Read only from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration (no .env file is read by the code)."""

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    database_url: str
    app_env: str = "local"
    log_level: str = "INFO"
    resume_max_upload_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    resume_storage_dir: Path = Path("data/resumes")


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings. Use as a FastAPI dependency."""
    return Settings()  # type: ignore[call-arg]
