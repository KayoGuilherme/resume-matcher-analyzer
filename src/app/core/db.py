"""Async database engine and session dependency. Nothing is created at import time."""

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings, get_settings


class Base(DeclarativeBase):
    """Declarative base for all models. Its metadata is what Alembic compares migrations to."""


@lru_cache
def get_engine(settings: Settings) -> AsyncEngine:
    """Return the engine for these settings (created lazily, cached)."""
    return create_async_engine(settings.database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker(settings: Settings) -> async_sessionmaker[AsyncSession]:
    """Return the session factory for these settings (created lazily, cached)."""
    return async_sessionmaker(get_engine(settings), expire_on_commit=False)


async def get_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency yielding one database session per request."""
    async with get_sessionmaker(settings)() as session:
        yield session
