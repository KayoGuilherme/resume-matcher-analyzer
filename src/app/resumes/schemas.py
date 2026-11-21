"""Response models for resumes."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.ai.extraction.models import ExtractionResult
from app.ai.parsing.models import FileType, ParsingIssue
from app.core.processing import ProcessingError, ProcessingStatus

# Shared with jobs; the resume API names are kept.
ResumeStatus = ProcessingStatus
ResumeError = ProcessingError


class ResumeMetadata(BaseModel):
    """Facts about how the resume was parsed."""

    parser: str
    character_count: int
    word_count: int
    table_count: int
    image_count: int


class ResumeSummary(BaseModel):
    """A resume without its text (used in lists)."""

    id: uuid.UUID
    original_filename: str
    file_type: FileType
    size_bytes: int
    sha256: str
    page_count: int | None
    metadata: ResumeMetadata
    issues: list[ParsingIssue]
    created_at: datetime
    status: ResumeStatus = "uploaded"
    error: ResumeError | None = None


class ResumeDetail(ResumeSummary):
    """A resume with its extracted text and the extraction of its last successful processing."""

    text: str
    extraction: ExtractionResult | None = None
