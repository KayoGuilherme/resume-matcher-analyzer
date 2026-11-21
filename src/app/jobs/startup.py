"""Checks and recovery for jobs, run once when the application starts."""

import asyncio
import logging
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.ai.embeddings.dimension import check_embedding_dimension
from app.core.config import Settings
from app.core.db import get_sessionmaker
from app.core.processing import PROCESSING_MESSAGES
from app.jobs.repository import JobRepository

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 5


class JobStartupRepository(Protocol):
    async def requirements_embedding_dimension(self) -> int | None: ...

    async def mark_interrupted(self, message: str) -> int: ...


async def run_job_startup_checks(repository: JobStartupRepository, settings: Settings) -> None:
    """Verify the vector dimension of `job_requirements`, then fail the jobs whose processing
    died with the last process. Both are skipped (with a warning) when the table is missing."""
    in_database = await repository.requirements_embedding_dimension()
    if in_database is None:
        logger.warning("job startup checks skipped: the job_requirements table does not exist yet")
        return
    check_embedding_dimension(settings.embedding_dimension, in_database, table="job_requirements")
    interrupted = await repository.mark_interrupted(PROCESSING_MESSAGES["processing_interrupted"])
    if interrupted:
        logger.warning("interrupted job processing recovered", extra={"job_count": interrupted})


async def run_jobs_startup(settings: Settings) -> None:
    """Called from the lifespan. An unreachable database only skips the checks (with a warning).
    A dimension mismatch raises and stops the application."""
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
            async with get_sessionmaker(settings)() as session:
                await run_job_startup_checks(JobRepository(session), settings)
    except (OSError, SQLAlchemyError) as error:
        logger.warning(
            "job startup checks skipped: the database is not reachable",
            extra={"exception_type": type(error).__name__},
        )
