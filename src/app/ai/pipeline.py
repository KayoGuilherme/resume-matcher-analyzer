"""Orchestrates the resume processing steps: extract -> chunk -> embed.

Pure orchestration over Pydantic models: no database, no HTTP. Persisting the result is the
service's job.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.ai.embeddings.base import EmbeddingClient
from app.ai.extraction.chunking import ChunkDraft, build_chunks
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
