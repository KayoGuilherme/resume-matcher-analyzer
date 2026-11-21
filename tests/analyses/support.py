"""Helpers for the analyses tests that need a real database: stored resumes and jobs."""

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.models import Analysis
from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.jobs.models import Job
from app.resumes.models import Resume


async def clean_session() -> AsyncGenerator[AsyncSession]:
    """A session on an empty database (every table the analyses touch is emptied before and
    after). Use it from a fixture in the test module."""
    if not os.environ.get("DATABASE_URL"):
        pytest.fail("DATABASE_URL must be set for integration tests")
    get_settings.cache_clear()
    settings = get_settings()
    engine = get_engine(settings)

    async def clear() -> None:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM analysis"))
            await connection.execute(text("DELETE FROM resume"))
            await connection.execute(text("DELETE FROM job"))
            await connection.execute(text("DELETE FROM candidate_profile"))

    await clear()
    async with get_sessionmaker(settings)() as db_session:
        yield db_session
    await clear()
    await engine.dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


def resume_row() -> Resume:
    return Resume(
        id=uuid.uuid4(),
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        original_filename="r.pdf",
        file_type="pdf",
        size_bytes=1,
        page_count=1,
        text="t",
        parsing_metadata={},
        issues=[],
        created_at=datetime.now(UTC),
    )


def job_row() -> Job:
    return Job(
        id=uuid.uuid4(),
        title="Backend",
        company=None,
        description="d",
        requirements_text=None,
        created_at=datetime.now(UTC),
    )


def analysis_row(
    resume_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    status: str = "processing",
    cache_key: str = "key",
    result: dict[str, object] | None = None,
) -> Analysis:
    return Analysis(
        id=uuid.uuid4(),
        resume_id=resume_id,
        job_id=job_id,
        status=status,
        cache_key=cache_key,
        result=result,
        created_at=datetime.now(UTC),
    )
