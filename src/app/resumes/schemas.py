"""Response models for resumes."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.ai.parsing.models import FileType, ParsingIssue


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


class ResumeDetail(ResumeSummary):
    """A resume with its extracted text."""

    text: str
