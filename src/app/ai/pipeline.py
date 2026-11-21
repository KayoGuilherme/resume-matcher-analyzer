"""Orchestrates the processing steps: extract -> (chunk) -> embed, for resumes and jobs.

Pure orchestration over Pydantic models: no database, no HTTP. Persisting the result is the
service's job.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.ai.embeddings.base import EmbeddingClient
from app.ai.extraction.chunking import ChunkDraft, build_chunks
from app.ai.extraction.job import extract_job
from app.ai.extraction.job_models import JobExtractionResult, JobRequirement
from app.ai.extraction.models import ExtractionResult
from app.ai.extraction.resume import extract_resume
from app.ai.llm.base import LLMClient
from app.ai.prompts.loader import Prompt


class EmbeddedChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk: ChunkDraft
    embedding: list[float]


class ProcessedResume(BaseModel):
    """Everything to store for a processed resume."""

    extraction: ExtractionResult
    chunks: list[EmbeddedChunk]
    embedding_model: str


async def process_resume_text(
    text: str,
    llm: LLMClient,
    embedder: EmbeddingClient,
    now: datetime,
    prompt: Prompt | None = None,
) -> ProcessedResume:
    extraction = await extract_resume(llm, text, now, prompt)
    drafts = build_chunks(extraction.resume)
    vectors = await embedder.embed([draft.text for draft in drafts]) if drafts else []
    return ProcessedResume(
        extraction=extraction,
        chunks=[
            EmbeddedChunk(chunk=draft, embedding=vector)
            for draft, vector in zip(drafts, vectors, strict=True)
        ],
        embedding_model=embedder.model_name,
    )


class EmbeddedRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement: JobRequirement
    position: int  # the order of the requirements in the extraction
    embedding: list[float]


class ProcessedJob(BaseModel):
    """Everything to store for a processed job."""

    extraction: JobExtractionResult
    requirements: list[EmbeddedRequirement]
    embedding_model: str


async def process_job_text(
    text: str,
    llm: LLMClient,
    embedder: EmbeddingClient,
    now: datetime,
    prompt: Prompt | None = None,
) -> ProcessedJob:
    """Extract the requirements of a posting and embed each requirement's `text`."""
    extraction = await extract_job(llm, text, now, prompt)
    requirements = extraction.job.requirements
    vectors = await embedder.embed([r.text for r in requirements]) if requirements else []
    return ProcessedJob(
        extraction=extraction,
        requirements=[
            EmbeddedRequirement(requirement=requirement, position=position, embedding=vector)
            for position, (requirement, vector) in enumerate(
                zip(requirements, vectors, strict=True)
            )
        ],
        embedding_model=embedder.model_name,
    )
