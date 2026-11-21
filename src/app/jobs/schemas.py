"""Request and response models for job positions."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from app.ai.extraction.job_models import JobExtractionResult
from app.core.processing import ProcessingError, ProcessingStatus

MAX_TITLE_CHARS = 200
MAX_COMPANY_CHARS = 200
MAX_TEXT_CHARS = 50_000

Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITLE_CHARS)
]
Company = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_COMPANY_CHARS)]
Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT_CHARS)
]
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_TEXT_CHARS)]


class JobIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    company: Company | None = None
    description: Description
    requirements_text: OptionalText | None = None

    @field_validator("company", "requirements_text")
    @classmethod
    def _blank_means_none(cls, value: str | None) -> str | None:
        return value or None


class JobSummary(BaseModel):
    """A job without its texts (used in lists)."""

    id: uuid.UUID
    title: str
    company: str | None
    status: ProcessingStatus = "uploaded"
    error: ProcessingError | None = None
    created_at: datetime


class JobDetail(JobSummary):
    """A job with its texts and the extraction of its last successful processing."""

    description: str
    requirements_text: str | None
    extraction: JobExtractionResult | None = None
