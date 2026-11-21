"""Business rules for jobs: creating, reading, deleting and processing."""

import logging
import time
import uuid
from datetime import UTC, datetime

from app.ai.embeddings.base import EmbeddingClient
from app.ai.error_codes import processing_error_code
from app.ai.extraction.job import build_posting_text
from app.ai.llm.base import LLMClient
from app.ai.pipeline import process_job_text
from app.core.errors import DomainError
from app.core.processing import PROCESSING_MESSAGES, AlreadyProcessingError
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobDetail, JobIn, JobSummary

logger = logging.getLogger(__name__)


class JobNotFoundError(DomainError):
    status_code = 404
    code = "job_not_found"


class JobService:
    def __init__(self, repository: JobRepository) -> None:
        self._repository = repository

    async def create(self, data: JobIn) -> JobDetail:
        job = JobDetail(
            id=uuid.uuid4(),
            title=data.title,
            company=data.company,
            description=data.description,
            requirements_text=data.requirements_text,
            created_at=datetime.now(UTC),
        )
        await self._repository.add(job)
        logger.info("job created", extra={"job_id": str(job.id)})
        return job

    async def list_all(self) -> list[JobSummary]:
        return await self._repository.list_all()

    async def get(self, job_id: uuid.UUID) -> JobDetail:
        job = await self._repository.get(job_id)
        if job is None:
            raise JobNotFoundError("Job not found")
        return job

    async def delete(self, job_id: uuid.UUID) -> None:
        if not await self._repository.delete(job_id):
            raise JobNotFoundError("Job not found")
        logger.info("job deleted", extra={"job_id": str(job_id)})

    async def start_processing(self, job_id: uuid.UUID) -> JobDetail:
        """Mark the job `processing` (atomically) and return it; the work runs later."""
        if not await self._repository.begin_processing(job_id):
            if await self._repository.get(job_id) is None:
                raise JobNotFoundError("Job not found")
            raise AlreadyProcessingError("This job is already being processed")
        job = await self._repository.get(job_id)
        if job is None:  # deleted between the two calls
            raise JobNotFoundError("Job not found")
        logger.info("job processing started", extra={"job_id": str(job_id)})
        return job

    async def run_processing(
        self, job_id: uuid.UUID, llm: LLMClient, embedder: EmbeddingClient
    ) -> None:
        """Extract and embed a job that is `processing`, then store the result.

        Never raises for processing failures: they end as status `failed` with a safe error.
        """
        started = time.perf_counter()
        try:
            job = await self._repository.get(job_id)
            if job is None:
                logger.warning("job vanished", extra={"job_id": str(job_id)})
                return
            text = build_posting_text(job.description, job.requirements_text)
            processed = await process_job_text(text, llm, embedder, datetime.now(UTC))
            if not await self._repository.save_processed(job_id, processed):
                logger.warning("job deleted meanwhile", extra={"job_id": str(job_id)})
                return
        except Exception as error:
            code = processing_error_code(error)
            logger.warning(
                "job processing failed",
                extra={
                    "job_id": str(job_id),
                    "error_code": code,
                    "exception_type": type(error).__name__,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                },
            )
            await self._repository.set_failed(job_id, code, PROCESSING_MESSAGES[code])
            return
        logger.info(
            "job processing finished",
            extra={
                "job_id": str(job_id),
                "requirement_count": len(processed.requirements),
                "warning_codes": [w.code for w in processed.extraction.warnings],
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
