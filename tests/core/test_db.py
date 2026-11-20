import importlib
import sys
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings
from app.core.db import Base, get_engine, get_session, get_sessionmaker


def _settings() -> Settings:
    return Settings(database_url="postgresql+asyncpg://u:p@localhost:5432/x")


def test_importing_db_module_creates_no_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sys.modules.pop("app.core.db", None)

    module = importlib.import_module("app.core.db")

    assert not hasattr(module, "engine")


def test_engine_and_sessionmaker_are_cached_per_settings() -> None:
    settings = _settings()

    assert get_engine(settings) is get_engine(settings)
    assert get_sessionmaker(settings) is get_sessionmaker(settings)


async def test_get_session_yields_async_session_without_connecting() -> None:
    generator: AsyncGenerator[AsyncSession] = get_session(_settings())

    session = await anext(generator)
    assert isinstance(session, AsyncSession)
    await generator.aclose()


def test_base_is_a_declarative_base_with_metadata() -> None:
    assert issubclass(Base, DeclarativeBase)
    assert isinstance(Base.metadata, MetaData)
