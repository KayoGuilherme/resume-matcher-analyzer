"""Step b: semantic retrieval. The resume chunks most similar to a requirement, above a minimum.

Cosine similarity is computed exactly, in plain Python, over the chunks of one resume (a few
hundred): an approximate index with a per-resume filter could silently return fewer than k rows.
The CPU work runs once per analysis in a worker thread.
"""

import asyncio
import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.ai.extraction.job_models import Category, JobRequirement
from app.ai.matching.deterministic import Hints, Settled
from app.ai.matching.errors import EmbeddingModelMismatchError
from app.ai.matching.models import ChunkInput, JobInput, ResumeInput
from app.ai.matching.text import ResumeIndex, fold

MAX_SECTION_LINES = 6


@dataclass(frozen=True)
class ScoredChunk:
    chunk: ChunkInput
    similarity: float


@dataclass(frozen=True)
class Candidates:
    """What the judge may read for one requirement: resume chunks and, for requirements whose
    evidence is not chunked, the resume's own lines of the matching section."""

    chunks: tuple[ChunkInput, ...]
    lines: tuple[str, ...]


def _unit(vector: Sequence[float]) -> list[float] | None:
    norm = math.sqrt(math.fsum(x * x for x in vector))
    return None if norm == 0 else [x / norm for x in vector]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0 when either vector is all zeros."""
    left, right = _unit(a), _unit(b)
    if left is None or right is None:
        return 0.0
    return math.fsum(x * y for x, y in zip(left, right, strict=True))


class ChunkMatrix:
    """The chunks of a resume with their vectors normalized once."""

    def __init__(self, chunks: Sequence[ChunkInput]) -> None:
        self._rows = [(chunk, _unit(chunk.embedding)) for chunk in chunks]

    def rank(
        self, vector: Sequence[float], *, top_k: int, min_similarity: float
    ) -> list[ScoredChunk]:
        """At most `top_k` chunks with a similarity of at least `min_similarity`, most similar
        first (ties by position in the resume)."""
        query = _unit(vector)
        if query is None:
            return []
        scored = [
            ScoredChunk(chunk, math.fsum(x * y for x, y in zip(query, unit, strict=True)))
            for chunk, unit in self._rows
            if unit is not None
        ]
        kept = [item for item in scored if item.similarity >= min_similarity]
        kept.sort(key=lambda item: (-item.similarity, item.chunk.position))
        return kept[:top_k]


def rank_chunks(
    vector: Sequence[float],
    chunks: Sequence[ChunkInput],
    *,
    top_k: int,
    min_similarity: float,
) -> list[ScoredChunk]:
    return ChunkMatrix(chunks).rank(vector, top_k=top_k, min_similarity=min_similarity)


async def rank_chunks_async(
    vectors: Sequence[Sequence[float]],
    chunks: Sequence[ChunkInput],
    *,
    top_k: int,
    min_similarity: float,
) -> list[list[ScoredChunk]]:
    """The ranking of every requirement vector, computed in one worker thread."""

    def work() -> list[list[ScoredChunk]]:
        matrix = ChunkMatrix(chunks)
        return [matrix.rank(v, top_k=top_k, min_similarity=min_similarity) for v in vectors]

    return await asyncio.to_thread(work)


def ensure_comparable(resume: ResumeInput, job: JobInput) -> None:
    """Vectors are only comparable when they come from one embedding model and have one size."""
    if not resume.chunks or not job.requirements:
        return  # nothing to compare
    if resume.embedding_model != job.embedding_model:
        raise EmbeddingModelMismatchError("The resume and the job use different embedding models")
    sizes = {len(chunk.embedding) for chunk in resume.chunks}
    sizes |= {len(item.embedding) for item in job.requirements}
    if len(sizes) > 1:
        raise EmbeddingModelMismatchError("The resume and the job vectors have different sizes")


def section_lines(index: ResumeIndex, category: Category) -> list[str]:
    """For `education` and `language` requirements: the resume's lines that belong to the
    education, certification or language entries, because those sections are not chunked."""
    resume = index.input.resume
    terms: list[str] = []
    if category == "education":
        for education in resume.education:
            terms += [education.institution, education.degree or "", education.field_of_study or ""]
        for certification in resume.certifications:
            terms += [certification.name, certification.issuer or ""]
    elif category == "language":
        terms += [language.name for language in resume.languages]
    folded = [term for term in dict.fromkeys(fold(t) for t in terms) if term]
    return index.lines_containing(folded, MAX_SECTION_LINES) if folded else []


def candidates(
    requirement: JobRequirement,
    ranked: Sequence[ScoredChunk],
    hints: Hints,
    index: ResumeIndex,
) -> Candidates | Settled:
    """The similar chunks, then the chunks that contain a keyword, then the section lines. With
    none of them the requirement is settled as `missing`, without an LLM call."""
    chunks: list[ChunkInput] = []
    seen: set[object] = set()
    for chunk in [item.chunk for item in ranked] + list(hints.keyword_chunks):
        if chunk.id not in seen:
            seen.add(chunk.id)
            chunks.append(chunk)
    lines = section_lines(index, requirement.category)
    if not chunks and not lines:
        return Settled("missing", (), "no_similar_content")
    return Candidates(chunks=tuple(chunks), lines=tuple(lines))
