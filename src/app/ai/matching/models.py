"""Models of the gap analysis: its inputs (plain data, no database rows), its result and the
schema the LLM judge answers with.

The inputs are small Pydantic models so that `ai/matching/` depends on no feature package: the
analyses service maps database rows and the profile to them.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.extraction.chunking import ChunkSection
from app.ai.extraction.job_models import Category, JobRequirement, PostingLanguage, Priority
from app.ai.extraction.models import ExtractionWarning, Resume

Verdict = Literal["met", "partial", "missing", "in_profile_not_in_resume"]
JudgeVerdict = Literal["met", "partial", "missing"]
DecidedBy = Literal["deterministic", "semantic", "judge", "profile"]
EvidenceSource = Literal["resume", "profile"]
StackLevel = Literal["learning", "working", "proficient", "expert"]
LanguageLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2", "native"]

MAX_EVIDENCE = 3


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# --- inputs ---------------------------------------------------------------------------------


class ChunkInput(_Frozen):
    """A resume chunk with its vector."""

    id: uuid.UUID
    section: ChunkSection
    experience_id: uuid.UUID | None
    position: int
    text: str
    embedding: list[float]


class ResumeInput(_Frozen):
    text: str  # the parsed text: every resume quote is checked against it
    resume: Resume
    chunks: list[ChunkInput]
    embedding_model: str


class RequirementInput(_Frozen):
    requirement: JobRequirement
    embedding: list[float]


class JobInput(_Frozen):
    language: PostingLanguage
    ats_keywords: list[str]
    requirements: list[RequirementInput]
    embedding_model: str


class ProfileStack(_Frozen):
    name: str  # normalized
    years: float
    level: StackLevel


class ProfileLanguage(_Frozen):
    name: str  # normalized
    level: LanguageLevel


class ProfileFacts(_Frozen):
    total_years_coding: float
    stacks: list[ProfileStack]
    languages: list[ProfileLanguage]
    notable_facts: list[str]


class AnalysisInput(_Frozen):
    resume: ResumeInput
    job: JobInput
    profile: ProfileFacts


class AnalysisSettings(_Frozen):
    """The settings that shape an analysis (a snapshot of the `ANALYSIS_*` configuration)."""

    top_k: int = Field(ge=1)
    min_similarity: float = Field(ge=0, le=1)
    max_requirements_per_call: int = Field(ge=1)
    max_llm_calls: int = Field(ge=1)


# --- result ---------------------------------------------------------------------------------


class Evidence(_Frozen):
    """A resume quote (verbatim) or a profile fact (as written, or composed from profile values)."""

    source: EvidenceSource
    quote: str


class RequirementFinding(BaseModel):
    requirement_id: uuid.UUID
    requirement_text: str
    category: Category
    priority: Priority
    priority_unclear: bool
    verdict: Verdict
    decided_by: DecidedBy
    evidence: list[Evidence]
    explanation: str
    flags: list[str]


class FoundKeyword(BaseModel):
    keyword: str
    matched_text: str  # as written in the resume


class AtsCoverage(BaseModel):
    found: list[FoundKeyword]
    missing: list[str]


class Provenance(BaseModel):
    prompt_name: str
    prompt_version: int
    llm_provider: str
    llm_model: str
    embedding_model: str
    llm_calls: int
    top_k: int
    min_similarity: float
    max_requirements_per_call: int
    max_llm_calls: int
    analyzed_at: datetime


class AnalysisResult(BaseModel):
    findings: list[RequirementFinding]
    ats_coverage: AtsCoverage
    warnings: list[ExtractionWarning]
    provenance: Provenance


# --- the schema the judge answers with (every field required: strict structured output) ------


class JudgeAnswer(BaseModel):
    requirement: int  # the number of the requirement in the batch, starting at 1
    verdict: JudgeVerdict
    quotes: list[str]
    explanation: str


class JudgeBatch(BaseModel):
    answers: list[JudgeAnswer]
