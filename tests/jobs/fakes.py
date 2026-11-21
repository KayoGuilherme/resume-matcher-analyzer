"""An in-memory stand-in for the job repository (no database)."""

import uuid

from app.ai.pipeline import ProcessedJob
from app.core.processing import ProcessingError
from app.jobs.schemas import JobDetail, JobSummary


class FakeJobRepository:
    def __init__(self) -> None:
        self.by_id: dict[uuid.UUID, JobDetail] = {}
        self.requirements: dict[uuid.UUID, ProcessedJob] = {}
        self.fail_on_save: Exception | None = None
        self.column_dimension: int | None = 1024
        self.interrupted_message: str | None = None

    async def add(self, job: JobDetail) -> None:
        self.by_id[job.id] = job

    async def get(self, job_id: uuid.UUID) -> JobDetail | None:
        return self.by_id.get(job_id)

    async def list_all(self) -> list[JobSummary]:
        newest_first = sorted(self.by_id.values(), key=lambda j: j.created_at, reverse=True)
        return [
            JobSummary(**j.model_dump(exclude={"description", "requirements_text", "extraction"}))
            for j in newest_first
        ]

    async def delete(self, job_id: uuid.UUID) -> bool:
        self.requirements.pop(job_id, None)
        return self.by_id.pop(job_id, None) is not None

    async def begin_processing(self, job_id: uuid.UUID) -> bool:
        job = self.by_id.get(job_id)
        if job is None or job.status == "processing":
            return False
        self.by_id[job_id] = job.model_copy(update={"status": "processing", "error": None})
        return True

    async def save_processed(self, job_id: uuid.UUID, processed: ProcessedJob) -> bool:
        if self.fail_on_save is not None:
            raise self.fail_on_save
        job = self.by_id.get(job_id)
        if job is None:
            return False
        self.by_id[job_id] = job.model_copy(
            update={"status": "ready", "error": None, "extraction": processed.extraction}
        )
        self.requirements[job_id] = processed
        return True

    async def set_failed(self, job_id: uuid.UUID, code: str, message: str) -> None:
        job = self.by_id.get(job_id)
        if job is not None:
            error = ProcessingError(code=code, message=message)
            self.by_id[job_id] = job.model_copy(update={"status": "failed", "error": error})

    async def mark_interrupted(self, message: str) -> int:
        self.interrupted_message = message
        count = 0
        for job_id, job in list(self.by_id.items()):
            if job.status == "processing":
                error = ProcessingError(code="processing_interrupted", message=message)
                self.by_id[job_id] = job.model_copy(update={"status": "failed", "error": error})
                count += 1
        return count

    async def requirements_embedding_dimension(self) -> int | None:
        return self.column_dimension
