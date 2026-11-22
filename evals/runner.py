"""Run the real pipeline on the eval cases and collect what the metrics need.

Per case, the resume and the job are processed once with the configured providers (extraction,
chunks, embeddings); the analysis, the screener, the suggestions and the score then run `runs`
times on those inputs, so consistency measures the judge, the screener and the suggestion step.
Nothing here touches a database, and no resume or job text leaves this module except to the
providers.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.ai.embeddings.base import EmbeddingClient
from app.ai.llm.base import LLMClient
from app.ai.matching.engine import analyze
from app.ai.matching.models import (
    AnalysisInput,
    AnalysisSettings,
    ChunkInput,
    JobInput,
    RequirementInput,
    ResumeInput,
)
from app.ai.matching.report import produce_report, vocabulary_of
from app.ai.matching.report_models import ReportSettings, ScoreSettings
from app.ai.matching.rewrites import build_corpus
from app.ai.matching.score import compute_score
from app.ai.parsing.quality import check_quality
from app.ai.pipeline import process_job_text, process_resume_text
from evals.dataset import Case
from evals.metrics import (
    CaseResult,
    RunRecord,
    checks_for,
    fabrication,
    match_expected,
)

DROPPED_QUOTES = "dropped_unverified_evidence"


@dataclass(frozen=True)
class Clients:
    llm: LLMClient
    embedder: EmbeddingClient


@dataclass(frozen=True)
class Settings:
    """The settings that shape one run of the pipeline (snapshots, like the analysis service)."""

    runs: int
    analysis: AnalysisSettings
    report: ReportSettings
    score: ScoreSettings


async def build_inputs(case: Case, clients: Clients, now: datetime) -> AnalysisInput:
    """Process the case's resume and job text like an upload would, and read the profile."""
    resume = await process_resume_text(case.resume_text, clients.llm, clients.embedder, now)
    job = await process_job_text(case.job_text, clients.llm, clients.embedder, now)
    return AnalysisInput(
        resume=ResumeInput(
            text=case.resume_text,
            resume=resume.extraction.resume,
            chunks=[
                ChunkInput(
                    id=uuid.uuid4(),
                    section=item.chunk.section,
                    experience_id=item.chunk.experience_id,
                    position=item.chunk.position,
                    text=item.chunk.text,
                    embedding=item.embedding,
                )
                for item in resume.chunks
            ],
            embedding_model=resume.embedding_model,
        ),
        job=JobInput(
            language=job.extraction.job.language,
            ats_keywords=job.extraction.job.ats_keywords,
            requirements=[
                RequirementInput(requirement=item.requirement, embedding=item.embedding)
                for item in job.requirements
            ],
            embedding_model=job.embedding_model,
        ),
        profile=case.profile_facts(),
    )


async def run_case(case: Case, clients: Clients, settings: Settings, now: datetime) -> CaseResult:
    inputs = await build_inputs(case, clients, now)
    issues = check_quality(case.parsed_document())
    matched = match_expected(case.expected, [r.requirement for r in inputs.job.requirements])
    corpus = build_corpus(inputs.resume.text, inputs.profile)
    vocabulary = vocabulary_of(inputs)

    records: list[RunRecord] = []
    for _ in range(settings.runs):
        result = await analyze(inputs, clients.llm, settings.analysis, now)
        stored = await produce_report(inputs, result, issues, clients.llm, settings.report, now)
        score = compute_score(result, issues, settings.score)
        verdicts = {finding.requirement_id: finding.verdict for finding in result.findings}
        kept = sum(1 for f in result.findings for e in f.evidence if e.source == "resume")
        dropped = sum(w.count for w in result.warnings if w.code == DROPPED_QUOTES)
        records.append(
            RunRecord(
                checks=checks_for(matched, verdicts),
                outcome=score.outcome,
                screener_decision=stored.screener.decision,
                screener_consistency=stored.screener.consistency,
                fabrication=fabrication(
                    result.findings,
                    inputs.resume.text,
                    stored.suggestions.accepted,
                    corpus,
                    vocabulary,
                ),
                quotes_kept=kept,
                quotes_dropped=dropped,
            )
        )
    return CaseResult(case.id, case.expected_outcome, records)


@dataclass(frozen=True)
class CaseError:
    case_id: str
    error_type: str  # the exception's class name: never its message


async def run_cases(
    cases: Sequence[Case], clients: Clients, settings: Settings, now: datetime
) -> tuple[list[CaseResult], list[CaseError]]:
    """Run every case; one that cannot finish is recorded as an error and the rest still run."""
    results: list[CaseResult] = []
    errors: list[CaseError] = []
    for case in cases:
        try:
            results.append(await run_case(case, clients, settings, now))
        except Exception as error:  # a provider or a pipeline failure: reported, never fatal
            errors.append(CaseError(case.id, type(error).__name__))
    return results, errors
