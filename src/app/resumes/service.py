"""Business rules for resumes: validation, de-duplication, parsing and storage."""

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import NamedTuple

from starlette.concurrency import run_in_threadpool

from app.ai.parsing import parse_document
from app.ai.parsing.detect import detect_file_type
from app.ai.parsing.models import UnreadableDocumentError
from app.ai.parsing.quality import check_quality
from app.core.errors import DomainError
from app.core.storage import FileStorage
from app.resumes.repository import ResumeRepository
from app.resumes.schemas import ResumeDetail, ResumeMetadata, ResumeSummary

logger = logging.getLogger(__name__)

MAX_FILENAME_LENGTH = 255
_MEGABYTE = 1024 * 1024


class FileTooLargeError(DomainError):
    status_code = 413
    code = "file_too_large"


class EmptyFileError(DomainError):
    status_code = 422
    code = "empty_file"


class UnsupportedFileTypeError(DomainError):
    status_code = 415
    code = "unsupported_file_type"


class UnreadableFileError(DomainError):
    status_code = 422
    code = "unreadable_file"


class NoExtractableTextError(DomainError):
    status_code = 422
    code = "no_extractable_text"


class ResumeNotFoundError(DomainError):
    status_code = 404
    code = "resume_not_found"


class UploadResult(NamedTuple):
    resume: ResumeDetail
    created: bool


def format_size_limit(limit: int) -> str:
    """`5242880` -> `5 MB`; sizes that are not whole megabytes are shown in bytes."""
    if limit % _MEGABYTE == 0:
        return f"{limit // _MEGABYTE} MB"
    return f"{limit} bytes"


def _display_name(filename: str | None) -> str:
    """The uploaded name without directories or control characters (never used as a path)."""
    cleaned = (filename or "").replace("\x00", "").replace("\\", "/")
    return PurePosixPath(cleaned).name[:MAX_FILENAME_LENGTH] or "resume"


class ResumeService:
    def __init__(
        self, repository: ResumeRepository, storage: FileStorage, max_upload_bytes: int
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._max_upload_bytes = max_upload_bytes

    def _rejected[E: DomainError](self, error: E) -> E:
        # The reason code only: never the file name or any content.
        logger.info("resume upload rejected", extra={"reason": error.code})
        return error

    async def upload(self, filename: str | None, data: bytes) -> UploadResult:
        """Validate, parse and store a resume. Identical content returns the existing resume."""
        if len(data) > self._max_upload_bytes:
            raise self._rejected(
                FileTooLargeError(
                    "The file is larger than the "
                    f"{format_size_limit(self._max_upload_bytes)} limit for resume uploads."
                )
            )
        if not data:
            raise self._rejected(
                EmptyFileError("The file is empty. Upload a PDF or DOCX that contains your resume.")
            )
        file_type = detect_file_type(data)
        if file_type is None:
            raise self._rejected(
                UnsupportedFileTypeError(
                    "Only PDF and DOCX files are accepted. The content of this file is neither, "
                    "whatever its name says."
                )
            )

        sha256 = hashlib.sha256(data).hexdigest()
        existing = await self._repository.get_by_sha(sha256)
        if existing is not None:
            logger.info("resume upload duplicate", extra={"resume_id": str(existing.id)})
            return UploadResult(existing, created=False)

        try:
            document = await run_in_threadpool(parse_document, data, file_type)
        except UnreadableDocumentError:
            raise self._rejected(
                UnreadableFileError(
                    "The file could not be opened: it may be corrupted or password-protected. An "
                    "ATS could not open it either. Export a fresh PDF or DOCX from the original "
                    "editor."
                )
            ) from None
        if not document.text.strip():
            scanned = "This file looks scanned or image-only. " if document.image_count else ""
            raise self._rejected(
                NoExtractableTextError(
                    f"{scanned}No text could be extracted from it. An ATS reads the text layer of "
                    "a resume, so a file whose content is only images is read as blank. Export a "
                    "text-based PDF or DOCX from the original editor."
                )
            )

        issues = check_quality(document)
        resume = ResumeDetail(
            id=uuid.uuid4(),
            original_filename=_display_name(filename),
            file_type=file_type,
            size_bytes=len(data),
            sha256=sha256,
            page_count=document.page_count,
            metadata=ResumeMetadata(
                parser=document.parser,
                character_count=len(document.text),
                word_count=len(document.text.split()),
                table_count=document.table_count,
                image_count=document.image_count,
            ),
            issues=issues,
            created_at=datetime.now(UTC),
            text=document.text,
        )

        key = f"{sha256}.{file_type}"
        already_stored = await self._storage.exists(key)
        await self._storage.save(key, data)
        try:
            inserted = await self._repository.add(resume)
        except BaseException:
            if not already_stored:
                await self._storage.delete(key)
            raise
        if not inserted:
            # A concurrent identical upload won: return its resume; the stored bytes are the same.
            winner = await self._repository.get_by_sha(sha256)
            if winner is None:
                raise RuntimeError("Resume disappeared during a concurrent upload")
            logger.info("resume upload duplicate", extra={"resume_id": str(winner.id)})
            return UploadResult(winner, created=False)

        logger.info(
            "resume uploaded",
            extra={
                "resume_id": str(resume.id),
                "size_bytes": resume.size_bytes,
                "file_type": file_type,
                "issue_codes": [issue.code for issue in issues],
            },
        )
        return UploadResult(resume, created=True)

    async def list_all(self) -> list[ResumeSummary]:
        return await self._repository.list_all()

    async def get(self, resume_id: uuid.UUID) -> ResumeDetail:
        resume = await self._repository.get(resume_id)
        if resume is None:
            raise ResumeNotFoundError("Resume not found")
        return resume

    async def delete(self, resume_id: uuid.UUID) -> None:
        """Delete the row, then its file (an orphan file is harmless; a dangling row is not)."""
        removed = await self._repository.delete(resume_id)
        if removed is None:
            raise ResumeNotFoundError("Resume not found")
        sha256, file_type = removed
        try:
            await self._storage.delete(f"{sha256}.{file_type}")
        except OSError:
            logger.warning(
                "stored resume file could not be removed", extra={"resume_id": str(resume_id)}
            )
        logger.info("resume deleted", extra={"resume_id": str(resume_id)})
