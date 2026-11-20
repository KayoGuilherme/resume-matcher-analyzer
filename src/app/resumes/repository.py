"""Database access for resumes. No business rules."""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.ai.parsing.models import ParsingIssue
from app.resumes.models import Resume
from app.resumes.schemas import ResumeDetail, ResumeMetadata, ResumeSummary


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
    }


def _to_detail(row: Resume) -> ResumeDetail:
    return ResumeDetail(**_summary_fields(row), text=row.text)


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
        statement = select(Resume).options(defer(Resume.text)).order_by(Resume.created_at.desc())
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
