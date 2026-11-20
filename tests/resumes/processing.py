"""Helpers for the processing tests: a stored resume and AI fakes."""

import uuid
from datetime import UTC, datetime

from app.resumes.schemas import ResumeDetail, ResumeMetadata
from tests.ai.extraction.builders import RESUME_TEXT


def stored_resume(text: str = RESUME_TEXT, status: str = "uploaded") -> ResumeDetail:
    return ResumeDetail(
        id=uuid.uuid4(),
        original_filename="resume.pdf",
        file_type="pdf",
        size_bytes=10,
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        page_count=1,
        metadata=ResumeMetadata(
            parser="pdfplumber",
            character_count=len(text),
            word_count=1,
            table_count=0,
            image_count=0,
        ),
        issues=[],
        created_at=datetime(2026, 11, 20, tzinfo=UTC),
        text=text,
        status=status,  # type: ignore[arg-type]
    )
