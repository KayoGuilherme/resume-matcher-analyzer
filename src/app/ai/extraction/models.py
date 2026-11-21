"""Structured resume models.

`ExtractedResume` is what the LLM is asked for: no ids, no totals and no contact fields (there is
simply no field for them). `Resume` adds code-assigned ids. Every field is required (optional
values are `X | None`) so the schema also works with strict structured-output modes.
"""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

YearMonth = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class SkillLine(BaseModel):
    """One line of a skills section, as written, and the skills it names."""

    text: str
    names: list[str]


class ExtractedExperience(BaseModel):
    title: str
    company: str | None
    start: YearMonth | None
    end: YearMonth | None
    is_current: bool
    bullets: list[str]


class Education(BaseModel):
    institution: str
    degree: str | None
    field_of_study: str | None
    start_year: int | None
    end_year: int | None


class LanguageSkill(BaseModel):
    name: str
    level: str | None  # as written in the resume


class Certification(BaseModel):
    name: str
    issuer: str | None
    date: str | None  # as written in the resume


class ExtractedProject(BaseModel):
    name: str
    bullets: list[str]
    technologies: list[str]


class ExtractedResume(BaseModel):
    summary: str | None
    skills: list[SkillLine]
    experiences: list[ExtractedExperience]
    education: list[Education]
    languages: list[LanguageSkill]
    certifications: list[Certification]
    projects: list[ExtractedProject]


class Experience(ExtractedExperience):
    id: uuid.UUID


class Project(ExtractedProject):
    id: uuid.UUID


class Resume(BaseModel):
    summary: str | None
    skills: list[SkillLine]
    experiences: list[Experience]
    education: list[Education]
    languages: list[LanguageSkill]
    certifications: list[Certification]
    projects: list[Project]


class ExtractionWarning(BaseModel):
    code: str
    count: int


class ExtractionResult(BaseModel):
    """A resume plus how it was produced."""

    resume: Resume
    total_experience_months: int
    total_experience_years: float
    warnings: list[ExtractionWarning]
    prompt_name: str
    prompt_version: int
    llm_provider: str
    llm_model: str
    extracted_at: datetime
