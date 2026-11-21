"""Small builders so job extraction tests stay readable."""

from app.ai.extraction.job_models import (
    ExtractedJob,
    ExtractedKeyword,
    ExtractedRequirement,
)


def keyword(name: str, *synonyms: str) -> ExtractedKeyword:
    return ExtractedKeyword(name=name, synonyms=list(synonyms))


def requirement(
    source_text: str,
    *,
    text: str | None = None,
    category: str = "skill",
    priority: str = "unclear",
    min_years: float | None = None,
    keywords: list[ExtractedKeyword] | None = None,
) -> ExtractedRequirement:
    return ExtractedRequirement.model_validate(
        {
            "text": text if text is not None else source_text,
            "category": category,
            "priority": priority,
            "min_years": min_years,
            "keywords": [k.model_dump() for k in keywords or []],
            "source_text": source_text,
        }
    )


def job(
    *requirements: ExtractedRequirement,
    seniority: str | None = None,
    language: str = "en",
    responsibilities: list[str] | None = None,
    ats_keywords: list[str] | None = None,
) -> ExtractedJob:
    return ExtractedJob.model_validate(
        {
            "seniority": seniority,
            "language": language,
            "responsibilities": responsibilities or [],
            "ats_keywords": ats_keywords or [],
            "requirements": [r.model_dump() for r in requirements],
        }
    )
