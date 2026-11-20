import pytest
from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.main import create_app

_AI_ENVIRONMENT = (
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_TEMPERATURE",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_API_KEY",
    "EMBEDDING_BASE_URL",
)


@pytest.fixture(autouse=True)
def _no_ai_environment(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Tests must not depend on the developer's own provider configuration.

    `real_provider` tests are the exception: they exist to read it.
    """
    if request.node.get_closest_marker("real_provider") is None:
        for name in _AI_ENVIRONMENT:
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def app_settings() -> Settings:
    return Settings(database_url="postgresql+asyncpg://u:p@localhost:5432/test")


@pytest.fixture
def app(app_settings: Settings) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: app_settings
    return application
