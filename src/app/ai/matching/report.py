"""The screening report: the LLM part that is made once with the analysis (`produce_report`) and
the answer assembled whenever it is read (`build_report`).

`StoredReport` freezes everything that costs tokens or depends on rows that can change later (the
profile, the resume's parsing issues). The score, the actions and the disclaimer are computed from
it at read time, so the `SCORE_*` settings can be tuned without paying for the LLM again.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from app.ai.extraction.job_models import Keyword
from app.ai.extraction.models import ExtractionWarning
from app.ai.llm.base import LLMClient
from app.ai.matching import rewrites, screener
from app.ai.matching.actions import build_actions
from app.ai.matching.models import AnalysisInput, AnalysisResult, JobInput, ProfileFacts
from app.ai.matching.report_models import (
    MissingKeyword,
    Report,
    ReportProvenance,
    ReportSettings,
    ScoreSettings,
    ScreenerReport,
    StoredReport,
)
from app.ai.matching.score import compute_score
from app.ai.parsing.models import ParsingIssue
from app.ai.prompts.loader import load_prompt
from app.core.normalization import normalize_stack_name

_TECHNICAL_CATEGORIES = ("skill", "domain")


def missing_keywords(
    result: AnalysisResult, job: JobInput, profile: ProfileFacts
) -> list[MissingKeyword]:
    """The ATS keywords missing from the resume, in the job's order, each with whether the
    profile has it as a stack and which requirements of the job it belongs to."""
    stacks = {stack.name for stack in profile.stacks}
    linked: list[MissingKeyword] = []
    for keyword in result.ats_coverage.missing:
        name = normalize_stack_name(keyword)
        ids = [
            entry.requirement.id
            for entry in job.requirements
            if name in _requirement_names(entry.requirement.keywords)
        ]
        linked.append(
            MissingKeyword(keyword=keyword, in_profile=name in stacks, requirement_ids=ids)
        )
    return linked


def _requirement_names(keywords: Sequence[Keyword]) -> set[str]:
    return {name for keyword in keywords for name in (keyword.normalized, *keyword.synonyms)}


def vocabulary_of(inputs: AnalysisInput) -> frozenset[str]:
    """The technology names to look for in a suggestion (see `rewrites.build_vocabulary`)."""
    job_keywords = [
        name
        for entry in inputs.job.requirements
        if entry.requirement.category in _TECHNICAL_CATEGORIES
        for keyword in entry.requirement.keywords
        for name in (keyword.normalized, *keyword.synonyms)
    ]
    resume = inputs.resume.resume
    resume_names = [
        *(name for line in resume.skills for name in line.names),
        *(name for project in resume.projects for name in project.technologies),
    ]
    return rewrites.build_vocabulary(
        job_keywords=job_keywords,
        ats_keywords=inputs.job.ats_keywords,
        resume_names=resume_names,
        profile=inputs.profile,
    )


async def produce_report(
    inputs: AnalysisInput,
    result: AnalysisResult,
    issues: Sequence[ParsingIssue],
    llm: LLMClient,
    settings: ReportSettings,
    now: datetime,
) -> StoredReport:
    """Run the screener, then ask for the suggestions (one call, none without a target).

    Raises the LLM layer's errors; nothing is returned when a step fails.
    """
    screener_prompt = load_prompt(screener.PROMPT_NAME)
    suggestions_prompt = load_prompt(rewrites.PROMPT_NAME)

    simulated = await screener.run_screener(
        inputs.resume.text, inputs.job, llm, settings.screener_runs, screener_prompt
    )
    keywords = missing_keywords(result, inputs.job, inputs.profile)
    targets = rewrites.select_targets(result, keywords, settings.max_suggestions)
    suggestions, suggestion_calls = await rewrites.suggest(
        targets,
        inputs.resume.resume,
        inputs.profile,
        rewrites.build_corpus(inputs.resume.text, inputs.profile),
        vocabulary_of(inputs),
        llm,
        suggestions_prompt,
    )
    return StoredReport(
        language=inputs.job.language,
        screener=simulated,
        suggestions=suggestions,
        missing_keywords=keywords,
        issues=list(issues),
        provenance=ReportProvenance(
            screener_prompt_name=screener_prompt.name,
            screener_prompt_version=screener_prompt.version,
            suggestions_prompt_name=suggestions_prompt.name,
            suggestions_prompt_version=suggestions_prompt.version,
            llm_provider=llm.provider,
            llm_model=llm.model,
            llm_calls=settings.screener_runs + suggestion_calls,
            screener_runs=settings.screener_runs,
            max_suggestions=settings.max_suggestions,
            generated_at=now,
        ),
    )


def build_report(
    *,
    analysis_id: uuid.UUID,
    resume_id: uuid.UUID,
    job_id: uuid.UUID,
    result: AnalysisResult,
    stored: StoredReport,
    score_settings: ScoreSettings,
) -> Report:
    """The answer of `GET /analyses/{id}/report`, from stored data and the current settings."""
    score = compute_score(result, stored.issues, score_settings)
    simulated = ScreenerReport(
        **stored.screener.model_dump(),
        agrees_with_score=screener.agrees_with_score(stored.screener.decision, score.outcome),
    )
    rejections = [
        ExtractionWarning(code=f"suggestion_rejected_{item.code}", count=item.count)
        for item in stored.suggestions.rejected
    ]
    return Report(
        analysis_id=analysis_id,
        resume_id=resume_id,
        job_id=job_id,
        language=stored.language,
        disclaimer=screener.disclaimer(stored.language),
        score=score,
        score_settings=score_settings,
        screener=simulated,
        ats_coverage=result.ats_coverage,
        actions=build_actions(result, stored),
        suggestions=stored.suggestions.accepted,
        warnings=[*result.warnings, *rejections],
        provenance=stored.provenance,
    )
