"""The gap analysis: for every requirement of a job, decide whether the resume satisfies it.

Steps run in order and the first that can settle a requirement does: deterministic checks,
semantic retrieval, the LLM judge, then the profile cross-check on what is still missing or
partial. A final pass enforces the evidence rule on every finding whatever step produced it.
Pure orchestration over Pydantic models: no database, no HTTP; the LLM is the `LLMClient` protocol.
"""

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime

from app.ai.extraction.job_models import JobRequirement
from app.ai.extraction.models import ExtractionWarning
from app.ai.extraction.verify import is_verbatim, normalize
from app.ai.llm.base import LLMClient
from app.ai.matching import deterministic, judge, profile_check, retrieval
from app.ai.matching.ats import ats_coverage
from app.ai.matching.errors import AnalysisInvariantError
from app.ai.matching.messages import explain
from app.ai.matching.models import (
    MAX_EVIDENCE,
    AnalysisInput,
    AnalysisResult,
    AnalysisSettings,
    DecidedBy,
    Evidence,
    Provenance,
    RequirementFinding,
    Verdict,
)
from app.ai.matching.text import ResumeIndex
from app.ai.prompts.loader import Prompt, load_prompt

logger = logging.getLogger(__name__)


def _finding(
    requirement: JobRequirement,
    verdict: Verdict,
    decided_by: DecidedBy,
    evidence: Sequence[Evidence],
    explanation: str,
    flags: Sequence[str] = (),
) -> RequirementFinding:
    return RequirementFinding(
        requirement_id=requirement.id,
        requirement_text=requirement.text,
        category=requirement.category,
        priority=requirement.priority,
        priority_unclear=requirement.priority_unclear,
        verdict=verdict,
        decided_by=decided_by,
        evidence=list(evidence),
        explanation=explanation,
        flags=list(flags),
    )


def _settled(
    requirement: JobRequirement,
    outcome: deterministic.Settled,
    decided_by: DecidedBy,
    language: str,
) -> RequirementFinding:
    return _finding(
        requirement,
        outcome.verdict,
        decided_by,
        outcome.evidence,
        explain(outcome.code, language, outcome.params),
    )


def check_invariants(findings: Sequence[RequirementFinding], resume_text: str) -> None:
    """The evidence rule, for every finding. A break is a bug in a step and is never stored."""
    normalized = normalize(resume_text)
    for finding in findings:
        resume_quotes = [e.quote for e in finding.evidence if e.source == "resume"]
        profile_quotes = [e for e in finding.evidence if e.source == "profile"]
        if not finding.explanation.strip():
            raise AnalysisInvariantError("A finding has no explanation")
        if any(not is_verbatim(quote, normalized) for quote in resume_quotes):
            raise AnalysisInvariantError("A resume quote is not in the resume text")
        if finding.verdict in ("met", "partial"):
            if not 1 <= len(finding.evidence) <= MAX_EVIDENCE or profile_quotes:
                raise AnalysisInvariantError(f"A {finding.verdict} finding has invalid evidence")
        elif finding.verdict == "in_profile_not_in_resume":
            if not profile_quotes:
                raise AnalysisInvariantError("A profile finding has no profile evidence")
        elif finding.evidence:
            raise AnalysisInvariantError("A missing finding has evidence")


def _warnings(dropped: int, downgraded: int) -> list[ExtractionWarning]:
    warnings: list[ExtractionWarning] = []
    if dropped:
        warnings.append(ExtractionWarning(code="dropped_unverified_evidence", count=dropped))
    if downgraded:
        warnings.append(ExtractionWarning(code="verdicts_downgraded_to_missing", count=downgraded))
    return warnings


async def analyze(
    inputs: AnalysisInput,
    llm: LLMClient,
    settings: AnalysisSettings,
    now: datetime,
    prompt: Prompt | None = None,
) -> AnalysisResult:
    """Compare the resume with the job. Raises `AnalysisLimitError`, `JudgeIncompleteError`,
    `EmbeddingModelMismatchError`, `AnalysisInvariantError` or the LLM layer's errors."""
    retrieval.ensure_comparable(inputs.resume, inputs.job)
    prompt = prompt or load_prompt(judge.PROMPT_NAME)
    language = inputs.job.language
    index = ResumeIndex(inputs.resume)
    requirements = inputs.job.requirements

    findings: dict[int, RequirementFinding] = {}
    pending: list[tuple[int, deterministic.Hints]] = []
    for position, entry in enumerate(requirements):
        outcome = deterministic.check(entry.requirement, index, now.date())
        if isinstance(outcome, deterministic.Settled):
            findings[position] = _settled(entry.requirement, outcome, "deterministic", language)
        else:
            pending.append((position, outcome))

    ranked = await retrieval.rank_chunks_async(
        [requirements[position].embedding for position, _ in pending],
        inputs.resume.chunks,
        top_k=settings.top_k,
        min_similarity=settings.min_similarity,
    )
    queue: list[judge.QueueItem] = []
    for (position, hints), scored in zip(pending, ranked, strict=True):
        requirement = requirements[position].requirement
        found = retrieval.candidates(requirement, scored, hints, index)
        if isinstance(found, deterministic.Settled):
            findings[position] = _settled(requirement, found, "semantic", language)
        else:
            queue.append(judge.QueueItem(position, requirement, found, hints))

    judged = await judge.run(queue, inputs.resume.text, llm, settings, language, prompt)
    for queued in queue:
        judgment = judged.judgments[queued.index]
        findings[queued.index] = _finding(
            queued.requirement,
            judgment.verdict,
            "judge",
            judgment.evidence,
            judgment.explanation,
            judgment.flags,
        )

    ordered = [
        profile_check.check(entry.requirement, findings[position], inputs.profile, language)
        for position, entry in enumerate(requirements)
    ]
    check_invariants(ordered, inputs.resume.text)

    result = AnalysisResult(
        findings=ordered,
        ats_coverage=ats_coverage(inputs.job.ats_keywords, index.text),
        warnings=_warnings(judged.dropped_quotes, judged.downgraded),
        provenance=Provenance(
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            llm_provider=llm.provider,
            llm_model=llm.model,
            embedding_model=inputs.resume.embedding_model,
            llm_calls=judged.llm_calls,
            top_k=settings.top_k,
            min_similarity=settings.min_similarity,
            max_requirements_per_call=settings.max_requirements_per_call,
            max_llm_calls=settings.max_llm_calls,
            analyzed_at=now,
        ),
    )
    _log(result)
    return result


def _count(values: Sequence[str]) -> Mapping[str, int]:
    return dict(Counter(values))


def _log(result: AnalysisResult) -> None:
    logger.info(
        "analysis computed",
        extra={
            "requirement_count": len(result.findings),
            "verdicts": _count([f.verdict for f in result.findings]),
            "decided_by": _count([f.decided_by for f in result.findings]),
            "llm_calls": result.provenance.llm_calls,
            "warning_codes": [w.code for w in result.warnings],
        },
    )
