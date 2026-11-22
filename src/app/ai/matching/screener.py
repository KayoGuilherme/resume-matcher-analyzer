"""The simulated first-pass screener: an LLM with a rubric reads the resume text and the job and
decides `pass`, `borderline` or `reject`, several times; the report keeps the majority and how
much the runs agree.

It is a simulation and says so: the disclaimer is a constant here, never the model's words. The
screener sees only what a real one would: the resume text and the job's requirements and
keywords. It never receives the profile, the verdicts or the score, so its opinion stays
independent of the rest of the analysis.
"""

import logging
import time
from collections import Counter
from collections.abc import Sequence

from app.ai.llm.base import LLMClient, LLMInvalidOutputError
from app.ai.matching.models import JobInput
from app.ai.matching.report_models import (
    Outcome,
    ScreenerAnswer,
    ScreenerDecision,
    ScreenerResult,
    ScreenerRun,
)
from app.ai.prompts.loader import Prompt, load_prompt

logger = logging.getLogger(__name__)

PROMPT_NAME = "screener"
MAX_REASONS = 5
MAX_REASON_CHARS = 300

# The least favorable first: a tie goes to the earliest of the tied decisions.
_SEVERITY_ORDER: tuple[ScreenerDecision, ...] = ("reject", "borderline", "pass")
_OUTCOME_OF: dict[ScreenerDecision, Outcome] = {
    "pass": "likely_pass",
    "borderline": "borderline",
    "reject": "likely_reject",
}

DISCLAIMERS = {
    "en": (
        "This is a simulation: a language model applies a generic rubric to your resume text. "
        "It cannot see, and does not reproduce, the real ATS or screening process of the "
        "company, which may weigh things differently. Treat it as a hint, not as a prediction."
    ),
    "pt": (
        "Esta é uma simulação: um modelo de linguagem aplica um critério genérico ao texto do "
        "seu currículo. Ela não enxerga nem reproduz o ATS ou o processo de triagem real da "
        "empresa, que pode pesar as coisas de outra forma. Use-a como um indício, não como uma "
        "previsão."
    ),
}


def disclaimer(language: str) -> str:
    """Portuguese for a Portuguese job, English otherwise."""
    return DISCLAIMERS["pt" if language == "pt" else "en"]


def _language_name(language: str) -> str:
    return "Portuguese" if language == "pt" else "English"


def render_requirements(job: JobInput) -> str:
    return "\n".join(
        f"[{entry.requirement.priority}] {entry.requirement.text}" for entry in job.requirements
    )


def render_keywords(job: JobInput) -> str:
    return ", ".join(job.ats_keywords)


def majority(decisions: Sequence[ScreenerDecision]) -> tuple[ScreenerDecision, float]:
    """The most frequent decision (a tie goes to the least favorable) and the share of runs that
    gave it, rounded to two decimals."""
    counts = Counter(decisions)
    top = max(counts.values())
    winner = next(d for d in _SEVERITY_ORDER if counts[d] == top)
    return winner, round(top / len(decisions), 2)


def _clean_reasons(reasons: Sequence[str]) -> list[str]:
    cleaned = [" ".join(reason.split())[:MAX_REASON_CHARS].strip() for reason in reasons]
    return [reason for reason in cleaned if reason][:MAX_REASONS]


def agrees_with_score(decision: ScreenerDecision, outcome: Outcome | None) -> bool | None:
    """Whether the screener's decision corresponds to the score's outcome; None without one."""
    if outcome is None:
        return None
    return _OUTCOME_OF[decision] == outcome


async def run_screener(
    resume_text: str,
    job: JobInput,
    llm: LLMClient,
    runs: int,
    prompt: Prompt | None = None,
) -> ScreenerResult:
    """Run the screener `runs` times, one after the other, and keep every run.

    Raises the LLM layer's errors; an answer without a usable reason is an invalid output.
    """
    prompt = prompt or load_prompt(PROMPT_NAME)
    rendered = prompt.render(
        resume=resume_text,
        requirements=render_requirements(job),
        keywords=render_keywords(job),
        language=_language_name(job.language),
    )
    started = time.perf_counter()
    collected: list[ScreenerRun] = []
    for _ in range(runs):
        answer = await llm.generate_structured(
            rendered.user, ScreenerAnswer, system=rendered.system
        )
        reasons = _clean_reasons(answer.reasons)
        if not reasons:
            raise LLMInvalidOutputError("The screener gave no reasons")
        collected.append(ScreenerRun(decision=answer.decision, reasons=reasons))

    decision, consistency = majority([run.decision for run in collected])
    logger.info(
        "screener finished",
        extra={
            "runs": runs,
            "decision": decision,
            "consistency": consistency,
            "decision_counts": dict(Counter(run.decision for run in collected)),
            "duration_ms": round((time.perf_counter() - started) * 1000),
        },
    )
    return ScreenerResult(decision=decision, consistency=consistency, runs=collected)
