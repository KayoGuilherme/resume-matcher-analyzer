"""Application settings. Read only from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration (no .env file is read by the code)."""

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    database_url: str
    app_env: str = "local"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings. Use as a FastAPI dependency."""
    return Settings()  # type: ignore[call-arg]
