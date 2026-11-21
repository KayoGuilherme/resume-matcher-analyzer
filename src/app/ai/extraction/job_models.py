"""Structured job models.

`ExtractedJob` is what the LLM is asked for: no ids, and a `priority` that may be `unclear`.
`Job` is the result: code-assigned ids, the priority decided from the posting's wording, a flag
for the cases where it could not be decided, and normalized keywords. Every field of the LLM
schema is required (optional values are `X | None`) so it also works with strict structured-output
modes.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.ai.extraction.models import ExtractionWarning

Seniority = Literal["junior", "mid", "senior"]
PostingLanguage = Literal["en", "pt", "other"]
Category = Literal["skill", "years", "language", "education", "domain", "soft"]
Priority = Literal["must_have", "nice_to_have"]
MAX_YEARS = 60
Years = Annotated[float, Field(ge=0, le=MAX_YEARS, allow_inf_nan=False)]


class ExtractedKeyword(BaseModel):
    name: str
    synonyms: list[str]


class ExtractedRequirement(BaseModel):
    text: str
    category: Category
    priority: Literal["must_have", "nice_to_have", "unclear"]
    min_years: Years | None
    keywords: list[ExtractedKeyword]
    source_text: str


class ExtractedJob(BaseModel):
    seniority: Seniority | None
    language: PostingLanguage
    responsibilities: list[str]
    ats_keywords: list[str]
    requirements: list[ExtractedRequirement]


class Keyword(BaseModel):
    name: str  # as the model gave it
    normalized: str
    synonyms: list[str]  # normalized, de-duplicated, without the keyword itself


class JobRequirement(BaseModel):
    id: uuid.UUID
    text: str
    category: Category
    priority: Priority
    priority_unclear: bool
    min_years: float | None
    keywords: list[Keyword]
    source_text: str


class Job(BaseModel):
    seniority: Seniority | None
    language: PostingLanguage
    responsibilities: list[str]
    ats_keywords: list[str]
    requirements: list[JobRequirement]


class JobExtractionResult(BaseModel):
    """A job plus how it was produced."""

    job: Job
    warnings: list[ExtractionWarning]
    prompt_name: str
    prompt_version: int
    llm_provider: str
    llm_model: str
    extracted_at: datetime
