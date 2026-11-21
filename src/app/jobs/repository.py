"""Database access for jobs. No business rules."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.ai.extraction.job_models import JobExtractionResult
from app.ai.pipeline import ProcessedJob
from app.core.processing import ProcessingError
from app.jobs.models import Job, JobRequirement
from app.jobs.schemas import JobDetail, JobSummary


@dataclass(frozen=True)
class StoredVectors:
    """The vectors of a job's requirements, by requirement id, and the models that made them."""

    vectors: dict[uuid.UUID, list[float]]
    embedding_models: set[str]


def _summary_fields(row: Job) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "company": row.company,
        "status": row.status,
        "error": (
            ProcessingError(code=row.error_code, message=row.error_message or "")
            if row.error_code
            else None
        ),
        "created_at": row.created_at,
    }


def _to_detail(row: Job) -> JobDetail:
    extraction = (
        JobExtractionResult.model_validate(row.extraction) if row.extraction is not None else None
    )
    return JobDetail(
        **_summary_fields(row),
        description=row.description,
        requirements_text=row.requirements_text,
        extraction=extraction,
    )


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job: JobDetail) -> None:
        self._session.add(
            Job(
                id=job.id,
                title=job.title,
                company=job.company,
                description=job.description,
                requirements_text=job.requirements_text,
                created_at=job.created_at,
                status=job.status,
            )
        )
        await self._session.commit()

    async def get(self, job_id: uuid.UUID) -> JobDetail | None:
        row = await self._session.get(Job, job_id)
        return None if row is None else _to_detail(row)

    async def list_all(self) -> list[JobSummary]:
        """All jobs, newest first, without loading their texts or extraction."""
        statement = (
            select(Job)
            .options(defer(Job.description), defer(Job.requirements_text), defer(Job.extraction))
            .order_by(Job.created_at.desc())
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [JobSummary(**_summary_fields(row)) for row in rows]

    async def delete(self, job_id: uuid.UUID) -> bool:
        """Delete the job (its requirements go with it). Returns whether it existed."""
        result = await self._session.execute(delete(Job).where(Job.id == job_id).returning(Job.id))
        deleted = result.scalar_one_or_none() is not None
        await self._session.commit()
        return deleted

    async def begin_processing(self, job_id: uuid.UUID) -> bool:
        """Atomically set `processing` unless it already is (and clear the previous error).

        One statement, so two simultaneous requests cannot both win. Returns whether this call
        started the processing; False also when the job does not exist.
        """
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status != "processing")
            .values(status="processing", error_code=None, error_message=None)
            .returning(Job.id)
        )
        started = (await self._session.execute(statement)).scalar_one_or_none() is not None
        await self._session.commit()
        return started

    async def save_processed(self, job_id: uuid.UUID, processed: ProcessedJob) -> bool:
        """Replace the extraction and all requirement rows and set `ready`, in one transaction.

        Returns False (nothing written) when the job was deleted meanwhile. On any error the
        transaction is rolled back, so the previous extraction and rows stay untouched.
        """
        try:
            statement = (
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status="ready",
                    error_code=None,
                    error_message=None,
                    extraction=processed.extraction.model_dump(mode="json"),
                )
                .returning(Job.id)
            )
            if (await self._session.execute(statement)).scalar_one_or_none() is None:
                await self._session.rollback()
                return False
            await self._session.execute(
                delete(JobRequirement).where(JobRequirement.job_id == job_id)
            )
            created_at = datetime.now(UTC)
            self._session.add_all(
                JobRequirement(
                    id=item.requirement.id,
                    job_id=job_id,
                    position=item.position,
                    text=item.requirement.text,
                    category=item.requirement.category,
                    priority=item.requirement.priority,
                    priority_unclear=item.requirement.priority_unclear,
                    min_years=item.requirement.min_years,
                    keywords=[k.model_dump() for k in item.requirement.keywords],
                    source_text=item.requirement.source_text,
                    embedding=item.embedding,
                    embedding_model=processed.embedding_model,
                    created_at=created_at,
                )
                for item in processed.requirements
            )
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise
        return True

    async def set_failed(self, job_id: uuid.UUID, code: str, message: str) -> None:
        """Mark a failed run. The previous extraction and requirements are left as they are."""
        await self._session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status="failed", error_code=code, error_message=message)
        )
        await self._session.commit()

    async def mark_interrupted(self, message: str) -> int:
        """Fail every job still `processing` (its background work died with the process)."""
        result = await self._session.execute(
            update(Job)
            .where(Job.status == "processing")
            .values(status="failed", error_code="processing_interrupted", error_message=message)
            .returning(Job.id)
        )
        count = len(result.all())
        await self._session.commit()
        return count

    async def get_requirement_vectors(self, job_id: uuid.UUID) -> StoredVectors:
        """The vectors of a job's requirements. Empty for an unknown id."""
        rows = (
            (
                await self._session.execute(
                    select(JobRequirement).where(JobRequirement.job_id == job_id)
                )
            )
            .scalars()
            .all()
        )
        return StoredVectors(
            vectors={row.id: [float(x) for x in row.embedding] for row in rows},
            embedding_models={row.embedding_model for row in rows},
        )

    async def requirements_embedding_dimension(self) -> int | None:
        """The size of `job_requirements.embedding`, or None if the table does not exist."""
        result = await self._session.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = to_regclass('job_requirements') AND attname = 'embedding' "
                "AND NOT attisdropped"
            )
        )
        declared = result.scalar_one_or_none()
        match = re.search(r"\((\d+)\)", declared or "")
        return int(match.group(1)) if match else None
