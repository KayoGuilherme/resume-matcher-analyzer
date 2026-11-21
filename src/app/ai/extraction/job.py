"""Extract a structured `Job` from a posting, using any `LLMClient`.

Verification, the correction round, dropping, priority decisions and keyword normalization are
the same for every provider. Nothing here logs posting text.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime

from app.ai.extraction.job_models import (
    ExtractedJob,
    ExtractedRequirement,
    Job,
    JobExtractionResult,
    JobRequirement,
    Keyword,
)
from app.ai.extraction.models import ExtractionWarning
from app.ai.extraction.priority import resolve_priority
from app.ai.extraction.verify import comparison_key, is_verbatim, normalize
from app.ai.llm.base import LLMClient
from app.ai.prompts.loader import Prompt, load_prompt
from app.core.normalization import fold_text, normalize_language_name, normalize_stack_name

logger = logging.getLogger(__name__)

PROMPT_NAME = "job_extraction"


def build_posting_text(description: str, requirements_text: str | None) -> str:
    """The text the model reads and every `source_text` is checked against."""
    if requirements_text and requirements_text.strip():
        return f"{description}\n\n{requirements_text}"
    return description


def _normalizer(requirement: ExtractedRequirement) -> Callable[[str], str]:
    return normalize_language_name if requirement.category == "language" else normalize_stack_name


def normalize_keywords(requirement: ExtractedRequirement) -> list[Keyword]:
    """Keywords with normalized names; synonyms normalized, de-duplicated, without the name."""
    normalizer = _normalizer(requirement)
    keywords: list[Keyword] = []
    seen: set[str] = set()
    for keyword in requirement.keywords:
        if not keyword.name.strip():
            continue
        normalized = normalizer(keyword.name)
        if normalized in seen:
            continue
        seen.add(normalized)
        synonyms: list[str] = []
        for synonym in keyword.synonyms:
            if not synonym.strip():
                continue
            candidate = normalizer(synonym)
            if candidate != normalized and candidate not in synonyms:
                synonyms.append(candidate)
        keywords.append(
            Keyword(name=keyword.name.strip(), normalized=normalized, synonyms=synonyms)
        )
    return keywords


def normalize_ats_keywords(keywords: list[str]) -> list[str]:
    """Normalized, de-duplicated, in order of first appearance."""
    result: list[str] = []
    for keyword in keywords:
        if not keyword.strip():
            continue
        normalized = normalize_stack_name(keyword)
        if normalized not in result:
            result.append(normalized)
    return result


def dedupe_requirements(requirements: list[ExtractedRequirement]) -> list[ExtractedRequirement]:
    """Keep the first of requirements with the same source text and the same statement."""
    seen: set[tuple[str, str]] = set()
    kept: list[ExtractedRequirement] = []
    for requirement in requirements:
        key = (comparison_key(requirement.source_text), fold_text(requirement.text))
        if key not in seen:
            seen.add(key)
            kept.append(requirement)
    return kept


def _unverified_texts(extracted: ExtractedJob, posting_text: str) -> list[str]:
    normalized = normalize(posting_text)
    texts = [r.source_text for r in extracted.requirements]
    texts += extracted.responsibilities
    return [text for text in texts if not is_verbatim(text, normalized)]


def _corrections_block(unverified: list[str]) -> str:
    listed = "\n".join(f"- {text}" for text in unverified)
    return (
        "\nCorrection needed: these `source_text` and responsibility values from your previous "
        "answer are not in the posting exactly as written. Answer again in full. Copy each of "
        "them exactly from the posting, or leave that requirement or responsibility out:\n"
        f"{listed}\n"
    )


def _drop_unverified(extracted: ExtractedJob, posting_text: str) -> tuple[ExtractedJob, int]:
    normalized = normalize(posting_text)
    requirements = [r for r in extracted.requirements if is_verbatim(r.source_text, normalized)]
    responsibilities = [r for r in extracted.responsibilities if is_verbatim(r, normalized)]
    dropped = (len(extracted.requirements) - len(requirements)) + (
        len(extracted.responsibilities) - len(responsibilities)
    )
    cleaned = extracted.model_copy(
        update={"requirements": requirements, "responsibilities": responsibilities}
    )
    return cleaned, dropped


async def extract_job(
    llm: LLMClient, posting_text: str, now: datetime, prompt: Prompt | None = None
) -> JobExtractionResult:
    """Ask the model, verify every `source_text` and responsibility against `posting_text`,
    correct once, drop what is still not there, decide priorities from the wording, normalize
    keywords and assign ids."""
    prompt = prompt or load_prompt(PROMPT_NAME)
    rendered = prompt.render(posting_text=posting_text, corrections="")
    extracted = await llm.generate_structured(rendered.user, ExtractedJob, system=rendered.system)

    unverified = _unverified_texts(extracted, posting_text)
    corrected = bool(unverified)
    if unverified:
        rendered = prompt.render(
            posting_text=posting_text, corrections=_corrections_block(unverified)
        )
        extracted = await llm.generate_structured(
            rendered.user, ExtractedJob, system=rendered.system
        )
    extracted, dropped = _drop_unverified(extracted, posting_text)

    requirements: list[JobRequirement] = []
    unclear = 0
    for requirement in dedupe_requirements(extracted.requirements):
        priority, is_unclear = resolve_priority(
            requirement.source_text, posting_text, requirement.priority
        )
        unclear += is_unclear
        requirements.append(
            JobRequirement(
                id=uuid.uuid4(),
                text=requirement.text,
                category=requirement.category,
                priority=priority,
                priority_unclear=is_unclear,
                min_years=requirement.min_years,
                keywords=normalize_keywords(requirement),
                source_text=requirement.source_text,
            )
        )

    warnings: list[ExtractionWarning] = []
    if dropped:
        warnings.append(ExtractionWarning(code="dropped_unverified_items", count=dropped))
    if unclear:
        warnings.append(ExtractionWarning(code="priority_unclear_requirements", count=unclear))

    logger.info(
        "job extracted",
        extra={
            "requirement_count": len(requirements),
            "dropped_items": dropped,
            "unclear_priorities": unclear,
            "correction_round": corrected,
        },
    )
    return JobExtractionResult(
        job=Job(
            seniority=extracted.seniority,
            language=extracted.language,
            responsibilities=extracted.responsibilities,
            ats_keywords=normalize_ats_keywords(extracted.ats_keywords),
            requirements=requirements,
        ),
        warnings=warnings,
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        llm_provider=llm.provider,
        llm_model=llm.model,
        extracted_at=now,
    )
