import pytest
from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def app_settings() -> Settings:
    return Settings(database_url="postgresql+asyncpg://u:p@localhost:5432/test")


@pytest.fixture
def app(app_settings: Settings) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: app_settings
    return application
