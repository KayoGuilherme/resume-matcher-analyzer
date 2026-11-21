"""Recovery for analyses, run once when the application starts."""

import asyncio
import logging
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.analyses.repository import AnalysisRepository
from app.core.config import Settings
from app.core.db import get_sessionmaker
from app.core.processing import PROCESSING_MESSAGES

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 5


class AnalysisStartupRepository(Protocol):
    async def mark_interrupted(self, message: str) -> int: ...


async def run_analysis_startup_checks(repository: AnalysisStartupRepository) -> None:
    """Fail the analyses whose background work died with the last process."""
    interrupted = await repository.mark_interrupted(PROCESSING_MESSAGES["processing_interrupted"])
    if interrupted:
        logger.warning("interrupted analyses recovered", extra={"analysis_count": interrupted})


async def run_analyses_startup(settings: Settings) -> None:
    """Called from the lifespan. An unreachable database, or one that has not been migrated yet,
    only skips the recovery (with a warning): the application still starts."""
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
            async with get_sessionmaker(settings)() as session:
                await run_analysis_startup_checks(AnalysisRepository(session))
    except (OSError, SQLAlchemyError) as error:
        logger.warning(
            "analysis startup checks skipped: the database is not reachable or not migrated",
            extra={"exception_type": type(error).__name__},
        )
