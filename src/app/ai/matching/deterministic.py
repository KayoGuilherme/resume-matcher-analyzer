"""Step a: checks that prove a requirement in code, without embeddings or the LLM.

These checks only ever *prove*: a literal keyword in the resume, enough years computed from the
resume's dates, a language level that reaches the asked one. When they do not prove, they settle
nothing (the only exception is an education requirement when the resume has no education or
certification entry at all) and hand `Hints` to the next steps.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app.ai.extraction.experience import total_experience_months
from app.ai.extraction.job_models import JobRequirement
from app.ai.extraction.models import Experience
from app.ai.matching.levels import meets, parse_level
from app.ai.matching.models import MAX_EVIDENCE, ChunkInput, Evidence, LanguageLevel
from app.ai.matching.text import ResumeIndex, fold, keyword_forms
from app.core.normalization import normalize_language_name


@dataclass(frozen=True)
class Settled:
    """A verdict that the step can prove. `code` and `params` pick the system's explanation."""

    verdict: Literal["met", "missing"]
    evidence: tuple[Evidence, ...]
    code: str
    params: dict[str, str | float] = field(default_factory=dict)


@dataclass(frozen=True)
class Hints:
    """What the step learned without settling: used by retrieval and shown to the judge."""

    keyword_chunks: tuple[ChunkInput, ...] = ()
    resume_years: float | None = None
    resume_language_level: str | None = None  # as the resume wrote it
    required_level: LanguageLevel | None = None


def check(requirement: JobRequirement, index: ResumeIndex, today: date) -> Settled | Hints:
    language = requirement.category == "language"
    forms = [
        form
        for keyword in requirement.keywords
        for form in keyword_forms(keyword, language=language)
    ]
    chunks = tuple(index.chunks_matching(forms, allow_ambiguous=True)) if forms else ()

    if language:
        outcome = _language_level(requirement, index, chunks)
    elif requirement.min_years is not None:
        outcome = _years(requirement.min_years, forms, index, today, chunks)
    else:
        outcome = _keyword(forms, index, chunks)

    if isinstance(outcome, Settled):
        return outcome
    if requirement.category == "education" and _no_education_section(index):
        return Settled("missing", (), "education_section_absent")
    return outcome


def _no_education_section(index: ResumeIndex) -> bool:
    resume = index.input.resume
    return not resume.education and not resume.certifications


def _keyword(
    forms: list[str], index: ResumeIndex, chunks: tuple[ChunkInput, ...]
) -> Settled | Hints:
    if not forms:
        return Hints(keyword_chunks=chunks)
    quotes = index.passages(forms, MAX_EVIDENCE)
    if not quotes:
        return Hints(keyword_chunks=chunks)
    first = next((m for m in index.text.find(forms) if not m.ambiguous), None)
    return Settled(
        "met",
        tuple(Evidence(source="resume", quote=quote) for quote in quotes),
        "keyword_found",
        {"keyword": first.text if first else ""},
    )


def _recency(experience: Experience) -> str:
    return "9999-99" if experience.is_current else (experience.end or experience.start or "")


def _years(
    min_years: float,
    forms: list[str],
    index: ResumeIndex,
    today: date,
    chunks: tuple[ChunkInput, ...],
) -> Settled | Hints:
    resume = index.input.resume
    if forms:
        selected = index.experiences_mentioning(forms)
    else:
        selected = [(experience, []) for experience in resume.experiences]
    counted = [
        (experience, shown)
        for experience, shown in selected
        if total_experience_months([experience], today).months > 0
    ]
    months = total_experience_months([experience for experience, _ in counted], today).months
    years = round(months / 12, 1)
    if months < min_years * 12:
        return Hints(keyword_chunks=chunks, resume_years=years)

    quotes: list[str] = []
    for experience, shown in sorted(counted, key=lambda item: _recency(item[0]), reverse=True):
        bullet = (shown or experience.bullets or [""])[0]
        if bullet.strip():
            quotes.append(bullet)
    if not quotes:  # years that cannot be quoted are not proof
        return Hints(keyword_chunks=chunks, resume_years=years)
    return Settled(
        "met",
        tuple(Evidence(source="resume", quote=quote) for quote in quotes[:MAX_EVIDENCE]),
        "years_reached",
        {"years": years, "required": min_years},
    )


def _language_level(
    requirement: JobRequirement, index: ResumeIndex, chunks: tuple[ChunkInput, ...]
) -> Settled | Hints:
    required = parse_level(requirement.text)
    names = {fold(keyword.normalized) for keyword in requirement.keywords}
    listed: str | None = None
    for entry in index.input.resume.languages:
        if fold(normalize_language_name(entry.name)) not in names:
            continue
        listed = entry.level
        if not meets(parse_level(entry.level or ""), required):
            continue
        quote = _language_passage(index, entry.name, entry.level)
        if quote:
            evidence = (Evidence(source="resume", quote=quote),)
            if entry.level:
                params: dict[str, str | float] = {"language": entry.name, "level": entry.level}
                return Settled("met", evidence, "language_level_reached", params)
            return Settled("met", evidence, "language_listed", {"language": entry.name})
    return Hints(keyword_chunks=chunks, resume_language_level=listed, required_level=required)


def _language_passage(index: ResumeIndex, name: str, level: str | None) -> str | None:
    """The resume's own line about the language, preferring one that also shows the level."""
    passages = index.passages([fold(name)], 10, allow_ambiguous=True)
    if level:
        with_level = [p for p in passages if fold(level) in fold(p)]
        if with_level:
            return with_level[0]
    return passages[0] if passages else None
