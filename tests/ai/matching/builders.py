"""Small builders so matching tests stay readable."""

import uuid
from collections.abc import Sequence

from app.ai.extraction.job_models import JobRequirement, Keyword
from app.ai.extraction.models import (
    Certification,
    Education,
    Experience,
    LanguageSkill,
    Resume,
    SkillLine,
)
from app.ai.matching.models import (
    ChunkInput,
    JobInput,
    ProfileFacts,
    ProfileLanguage,
    ProfileStack,
    RequirementInput,
    ResumeInput,
)
from app.core.normalization import normalize_language_name, normalize_stack_name


def kw(name: str, *synonyms: str, language: bool = False) -> Keyword:
    normalize = normalize_language_name if language else normalize_stack_name
    normalized = normalize(name)
    return Keyword(
        name=name,
        normalized=normalized,
        # like the job extraction: normalized, without the keyword itself
        synonyms=[s for s in dict.fromkeys(normalize(x) for x in synonyms) if s != normalized],
    )


def req(
    text: str,
    *,
    category: str = "skill",
    priority: str = "must_have",
    priority_unclear: bool = False,
    min_years: float | None = None,
    keywords: Sequence[Keyword] = (),
    source_text: str | None = None,
    vector: Sequence[float] = (1.0, 0.0),
) -> RequirementInput:
    return RequirementInput(
        requirement=JobRequirement.model_validate(
            {
                "id": uuid.uuid4(),
                "text": text,
                "category": category,
                "priority": priority,
                "priority_unclear": priority_unclear,
                "min_years": min_years,
                "keywords": [keyword.model_dump() for keyword in keywords],
                "source_text": source_text or text,
            }
        ),
        embedding=list(vector),
    )


def chunk(
    text: str,
    position: int = 0,
    vector: Sequence[float] = (0.0, 1.0),
    *,
    section: str = "experience",
) -> ChunkInput:
    return ChunkInput.model_validate(
        {
            "id": uuid.uuid4(),
            "section": section,
            "experience_id": None,
            "position": position,
            "text": text,
            "embedding": list(vector),
        }
    )


def exp(
    *bullets: str,
    title: str = "Backend Developer",
    start: str | None = "2020-01",
    end: str | None = "2021-12",
    is_current: bool = False,
) -> Experience:
    return Experience(
        id=uuid.uuid4(),
        title=title,
        company="ACME",
        start=start,
        end=end,
        is_current=is_current,
        bullets=list(bullets),
    )


def resume_input(
    text: str,
    *,
    chunks: Sequence[ChunkInput] = (),
    experiences: Sequence[Experience] = (),
    skills: Sequence[str] = (),
    education: Sequence[Education] = (),
    languages: Sequence[LanguageSkill] = (),
    certifications: Sequence[Certification] = (),
    embedding_model: str = "fake-embed",
) -> ResumeInput:
    return ResumeInput(
        text=text,
        resume=Resume(
            summary=None,
            skills=[SkillLine(text=line, names=[]) for line in skills],
            experiences=list(experiences),
            education=list(education),
            languages=list(languages),
            certifications=list(certifications),
            projects=[],
        ),
        chunks=list(chunks),
        embedding_model=embedding_model,
    )


def job_input(
    *requirements: RequirementInput,
    language: str = "en",
    ats_keywords: Sequence[str] = (),
    embedding_model: str = "fake-embed",
) -> JobInput:
    return JobInput.model_validate(
        {
            "language": language,
            "ats_keywords": list(ats_keywords),
            "requirements": list(requirements),
            "embedding_model": embedding_model,
        }
    )


def stack(name: str, years: float, level: str = "working") -> ProfileStack:
    return ProfileStack.model_validate(
        {"name": normalize_stack_name(name), "years": years, "level": level}
    )


def lang(name: str, level: str) -> ProfileLanguage:
    return ProfileLanguage.model_validate({"name": normalize_language_name(name), "level": level})


def profile(
    *,
    total_years: float = 5,
    stacks: Sequence[ProfileStack] = (),
    languages: Sequence[ProfileLanguage] = (),
    facts: Sequence[str] = (),
) -> ProfileFacts:
    return ProfileFacts(
        total_years_coding=total_years,
        stacks=list(stacks),
        languages=list(languages),
        notable_facts=list(facts),
    )
