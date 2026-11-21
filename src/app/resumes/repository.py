"""Database access for resumes. No business rules."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.ai.extraction.models import ExtractionResult
from app.ai.matching.models import ChunkInput
from app.ai.parsing.models import ParsingIssue
from app.ai.pipeline import ProcessedResume
from app.resumes.models import Resume, ResumeChunk
from app.resumes.schemas import ResumeDetail, ResumeError, ResumeMetadata, ResumeSummary


@dataclass(frozen=True)
class StoredChunks:
    """A resume's chunks with their vectors and the embedding models that made them."""

    chunks: list[ChunkInput]
    embedding_models: set[str]


def _values(resume: ResumeDetail) -> dict[str, Any]:
    return {
        "id": resume.id,
        "sha256": resume.sha256,
        "original_filename": resume.original_filename,
        "file_type": resume.file_type,
        "size_bytes": resume.size_bytes,
        "page_count": resume.page_count,
        "text": resume.text,
        "parsing_metadata": resume.metadata.model_dump(),
        "issues": [issue.model_dump() for issue in resume.issues],
        "created_at": resume.created_at,
        "status": resume.status,
        "error_code": resume.error.code if resume.error else None,
        "error_message": resume.error.message if resume.error else None,
        "extraction": resume.extraction.model_dump(mode="json") if resume.extraction else None,
    }


def _summary_fields(row: Resume) -> dict[str, Any]:
    return {
        "id": row.id,
        "original_filename": row.original_filename,
        "file_type": row.file_type,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "page_count": row.page_count,
        "metadata": ResumeMetadata.model_validate(row.parsing_metadata),
        "issues": [ParsingIssue.model_validate(issue) for issue in row.issues],
        "created_at": row.created_at,
        "status": row.status,
        "error": (
            ResumeError(code=row.error_code, message=row.error_message or "")
            if row.error_code
            else None
        ),
    }


def _to_detail(row: Resume) -> ResumeDetail:
    extraction = (
        ExtractionResult.model_validate(row.extraction) if row.extraction is not None else None
    )
    return ResumeDetail(**_summary_fields(row), text=row.text, extraction=extraction)


class ResumeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, resume: ResumeDetail) -> bool:
        """Insert unless the same content (sha256) exists. Returns whether a row was inserted."""
        statement = (
            insert(Resume)
            .values(**_values(resume))
            .on_conflict_do_nothing(index_elements=["sha256"])
            .returning(Resume.id)
        )
        inserted = (await self._session.execute(statement)).scalar_one_or_none() is not None
        await self._session.commit()
        return inserted

    async def get_by_sha(self, sha256: str) -> ResumeDetail | None:
        statement = select(Resume).where(Resume.sha256 == sha256)
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return None if row is None else _to_detail(row)

    async def get(self, resume_id: uuid.UUID) -> ResumeDetail | None:
        row = await self._session.get(Resume, resume_id)
        return None if row is None else _to_detail(row)

    async def list_all(self) -> list[ResumeSummary]:
        """All resumes, newest first, without loading their text."""
        statement = (
            select(Resume)
            .options(defer(Resume.text), defer(Resume.extraction))
            .order_by(Resume.created_at.desc())
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [ResumeSummary(**_summary_fields(row)) for row in rows]

    async def delete(self, resume_id: uuid.UUID) -> tuple[str, str] | None:
        """Delete the row; return its (sha256, file_type) to find the stored file, or None."""
        statement = (
            delete(Resume).where(Resume.id == resume_id).returning(Resume.sha256, Resume.file_type)
        )
        row = (await self._session.execute(statement)).one_or_none()
        await self._session.commit()
        return None if row is None else (row.sha256, row.file_type)

    async def begin_processing(self, resume_id: uuid.UUID) -> bool:
        """Atomically set `processing` unless it already is (and clear the previous error).

        One statement, so two simultaneous requests cannot both win. Returns whether this call
        started the processing; False also when the resume does not exist.
        """
        statement = (
            update(Resume)
            .where(Resume.id == resume_id, Resume.status != "processing")
            .values(status="processing", error_code=None, error_message=None)
            .returning(Resume.id)
        )
        started = (await self._session.execute(statement)).scalar_one_or_none() is not None
        await self._session.commit()
        return started

    async def save_processed(self, resume_id: uuid.UUID, processed: ProcessedResume) -> bool:
        """Replace the extraction and all chunks and set `ready`, in one transaction.

        Returns False (nothing written) when the resume was deleted meanwhile. On any error the
        transaction is rolled back, so the previous extraction and chunks stay untouched.
        """
        try:
            statement = (
                update(Resume)
                .where(Resume.id == resume_id)
                .values(
                    status="ready",
                    error_code=None,
                    error_message=None,
                    extraction=processed.extraction.model_dump(mode="json"),
                )
                .returning(Resume.id)
            )
            if (await self._session.execute(statement)).scalar_one_or_none() is None:
                await self._session.rollback()
                return False
            await self._session.execute(
                delete(ResumeChunk).where(ResumeChunk.resume_id == resume_id)
            )
            created_at = datetime.now(UTC)
            self._session.add_all(
                ResumeChunk(
                    id=uuid.uuid4(),
                    resume_id=resume_id,
                    section=item.chunk.section,
                    experience_id=item.chunk.experience_id,
                    position=item.chunk.position,
                    text=item.chunk.text,
                    embedding=item.embedding,
                    embedding_model=processed.embedding_model,
                    created_at=created_at,
                )
                for item in processed.chunks
            )
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise
        return True

    async def set_failed(self, resume_id: uuid.UUID, code: str, message: str) -> None:
        """Mark a failed run. The previous extraction and chunks are left as they are."""
        await self._session.execute(
            update(Resume)
            .where(Resume.id == resume_id)
            .values(status="failed", error_code=code, error_message=message)
        )
        await self._session.commit()

    async def mark_interrupted(self, message: str) -> int:
        """Fail every resume still `processing` (its background work died with the process)."""
        result = await self._session.execute(
            update(Resume)
            .where(Resume.status == "processing")
            .values(status="failed", error_code="processing_interrupted", error_message=message)
            .returning(Resume.id)
        )
        count = len(result.all())
        await self._session.commit()
        return count

    async def get_chunks(self, resume_id: uuid.UUID) -> StoredChunks:
        """The chunks of a resume in resume order, with their vectors. Empty for an unknown id."""
        rows = (
            (
                await self._session.execute(
                    select(ResumeChunk)
                    .where(ResumeChunk.resume_id == resume_id)
                    .order_by(ResumeChunk.position)
                )
            )
            .scalars()
            .all()
        )
        chunks = [
            ChunkInput.model_validate(
                {
                    "id": row.id,
                    "section": row.section,
                    "experience_id": row.experience_id,
                    "position": row.position,
                    "text": row.text,
                    "embedding": [float(x) for x in row.embedding],
                }
            )
            for row in rows
        ]
        return StoredChunks(chunks=chunks, embedding_models={row.embedding_model for row in rows})

    async def chunk_embedding_dimension(self) -> int | None:
        """The size of the `resume_chunk.embedding` column, or None if the table does not exist."""
        result = await self._session.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = to_regclass('resume_chunk') AND attname = 'embedding' "
                "AND NOT attisdropped"
            )
        )
        declared = result.scalar_one_or_none()
        match = re.search(r"\((\d+)\)", declared or "")
        return int(match.group(1)) if match else None
