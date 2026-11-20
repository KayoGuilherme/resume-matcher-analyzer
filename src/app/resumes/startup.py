"""Checks and recovery run once when the application starts."""

import asyncio
import logging
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.db import get_sessionmaker
from app.resumes.repository import ResumeRepository
from app.resumes.service import PROCESSING_MESSAGES

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 5


class EmbeddingDimensionMismatchError(RuntimeError):
    """The configured EMBEDDING_DIMENSION does not match the database. The app must not start."""


class StartupRepository(Protocol):
    async def chunk_embedding_dimension(self) -> int | None: ...

    async def mark_interrupted(self, message: str) -> int: ...


def check_embedding_dimension(configured: int, in_database: int | None) -> None:
    """Fail loudly when the vector column and the configuration disagree."""
    if in_database is None or in_database == configured:
        return
    raise EmbeddingDimensionMismatchError(
        f"EMBEDDING_DIMENSION is {configured} but the database column resume_chunk.embedding has "
        f"{in_database} dimensions. Set EMBEDDING_DIMENSION={in_database}, or follow the "
        "procedure in README.md, section 'Changing the embedding model', to change the model."
    )


async def run_startup_checks(repository: StartupRepository, settings: Settings) -> None:
    """Verify the vector dimension, then fail the resumes whose processing died with the last
    process. Both are skipped (with a warning) when the table does not exist yet."""
    in_database = await repository.chunk_embedding_dimension()
    if in_database is None:
        logger.warning("startup checks skipped: the resume_chunk table does not exist yet")
        return
    check_embedding_dimension(settings.embedding_dimension, in_database)
    interrupted = await repository.mark_interrupted(PROCESSING_MESSAGES["processing_interrupted"])
    if interrupted:
        logger.warning("interrupted processing recovered", extra={"resume_count": interrupted})


async def run_startup(settings: Settings) -> None:
    """Called from the lifespan. An unreachable database only skips the checks (with a warning):
    `/health` reports it. A dimension mismatch raises and stops the application."""
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
            async with get_sessionmaker(settings)() as session:
                await run_startup_checks(ResumeRepository(session), settings)
    except (OSError, SQLAlchemyError) as error:
        logger.warning(
            "startup checks skipped: the database is not reachable",
            extra={"exception_type": type(error).__name__},
        )
