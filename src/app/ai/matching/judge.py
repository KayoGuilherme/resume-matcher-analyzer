"""Step c: the LLM judge, plus the rule that makes its answers trustworthy.

The judge sees only the requirements that the cheaper steps did not settle, in batches, with the
resume passages that may show them. Whatever it answers is checked here: a quote that is not in
the resume text is dropped, and a `met` or `partial` answer left without a valid quote becomes
`missing`. The model is never asked to correct a rejected quote.
"""

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.ai.extraction.job_models import JobRequirement
from app.ai.extraction.verify import comparison_key, is_verbatim, normalize
from app.ai.llm.base import LLMClient
from app.ai.matching.deterministic import Hints
from app.ai.matching.errors import AnalysisLimitError, JudgeIncompleteError
from app.ai.matching.messages import explain
from app.ai.matching.models import (
    MAX_EVIDENCE,
    AnalysisSettings,
    Evidence,
    JudgeAnswer,
    JudgeBatch,
    JudgeVerdict,
)
from app.ai.matching.retrieval import Candidates
from app.ai.prompts.loader import Prompt, load_prompt

logger = logging.getLogger(__name__)

PROMPT_NAME = "gap_judge"
MIN_QUOTE_CHARS = 3
EVIDENCE_NOT_VERBATIM = "evidence_not_verbatim"


@dataclass(frozen=True)
class QueueItem:
    """A requirement that reached the judge, with what the earlier steps found."""

    index: int  # position of the requirement in the job
    requirement: JobRequirement
    candidates: Candidates
    hints: Hints


@dataclass(frozen=True)
class Judgment:
    verdict: JudgeVerdict
    evidence: tuple[Evidence, ...]
    explanation: str
    flags: tuple[str, ...] = ()
    dropped_quotes: int = 0
    downgraded: bool = False


@dataclass
class JudgeOutcome:
    judgments: dict[int, Judgment] = field(default_factory=dict)  # by QueueItem.index
    llm_calls: int = 0

    @property
    def dropped_quotes(self) -> int:
        return sum(j.dropped_quotes for j in self.judgments.values())

    @property
    def downgraded(self) -> int:
        return sum(j.downgraded for j in self.judgments.values())


def build_batches(queue: Sequence[QueueItem], size: int) -> list[list[QueueItem]]:
    return [list(queue[start : start + size]) for start in range(0, len(queue), size)]


def _format_years(value: float) -> str:
    return f"{value:g}"


def _requirement_block(number: int, item: QueueItem, passage_numbers: list[int]) -> str:
    requirement = item.requirement
    lines = [f"[R{number}] category: {requirement.category}", f"text: {requirement.text}"]
    if requirement.min_years is not None:
        lines.append(f"minimum years: {_format_years(requirement.min_years)}")
    keywords = [
        k.normalized + (f" (also: {', '.join(k.synonyms)})" if k.synonyms else "")
        for k in requirement.keywords
    ]
    if keywords:
        lines.append(f"keywords: {'; '.join(keywords)}")
    lines.append("candidate passages: " + (", ".join(f"P{n}" for n in passage_numbers) or "none"))
    hints = item.hints
    if hints.resume_years is not None:
        lines.append(
            "hint: computed from the resume's dates, the experience that shows this requirement "
            f"is {_format_years(hints.resume_years)} years"
        )
    if hints.required_level is not None:
        lines.append(f"hint: the level asked is {hints.required_level}")
    if hints.resume_language_level is not None:
        lines.append(f'hint: the resume lists this language as "{hints.resume_language_level}"')
    return "\n".join(lines)


def render_batch(batch: Sequence[QueueItem]) -> tuple[str, str]:
    """The passages (numbered once per call) and the requirements of one call."""
    numbers: dict[str, int] = {}
    passages: list[str] = []

    def number_of(text: str) -> int:
        if text not in numbers:
            passages.append(text)
            numbers[text] = len(passages)
        return numbers[text]

    blocks: list[str] = []
    for position, item in enumerate(batch, start=1):
        texts = [chunk.text for chunk in item.candidates.chunks] + list(item.candidates.lines)
        blocks.append(_requirement_block(position, item, [number_of(text) for text in texts]))
    rendered = "\n\n".join(f"[P{n}] {text}" for n, text in enumerate(passages, start=1))
    return rendered, "\n\n".join(blocks)


def verify_answer(answer: JudgeAnswer, normalized_resume: str, language: str) -> Judgment:
    """The evidence rule: valid quotes only, at most 3, and no valid quote means `missing`."""
    own = answer.explanation.strip()
    if answer.verdict == "missing":
        return Judgment("missing", (), own or explain("judge_missing", language))

    valid: list[str] = []
    seen: set[str] = set()
    invalid = 0
    for quote in answer.quotes:
        key = comparison_key(quote)
        if len(key) < MIN_QUOTE_CHARS or not is_verbatim(quote, normalized_resume):
            invalid += 1
        elif key not in seen:
            seen.add(key)
            valid.append(quote.strip())
    if not valid:
        return Judgment(
            "missing",
            (),
            explain(EVIDENCE_NOT_VERBATIM, language),
            (EVIDENCE_NOT_VERBATIM,),
            dropped_quotes=invalid,
            downgraded=True,
        )
    fallback = explain("judge_met" if answer.verdict == "met" else "judge_partial", language)
    return Judgment(
        answer.verdict,
        tuple(Evidence(source="resume", quote=quote) for quote in valid[:MAX_EVIDENCE]),
        own or fallback,
        dropped_quotes=invalid,
    )


async def run(
    queue: Sequence[QueueItem],
    resume_text: str,
    llm: LLMClient,
    settings: AnalysisSettings,
    language: str,
    prompt: Prompt | None = None,
) -> JudgeOutcome:
    """Judge every requirement of the queue. Raises `AnalysisLimitError` before any call when
    the batches needed exceed the call limit, `JudgeIncompleteError` when requirements stay
    unanswered after the second try."""
    outcome = JudgeOutcome()
    if not queue:
        return outcome
    batches = build_batches(queue, settings.max_requirements_per_call)
    if len(batches) > settings.max_llm_calls:
        raise AnalysisLimitError("The requirements to judge need more LLM calls than allowed")

    prompt = prompt or load_prompt(PROMPT_NAME)
    normalized = normalize(resume_text)

    async def ask(batch: list[QueueItem]) -> None:
        passages, requirements = render_batch(batch)
        rendered = prompt.render(passages=passages, requirements=requirements)
        answer = await llm.generate_structured(rendered.user, JudgeBatch, system=rendered.system)
        outcome.llm_calls += 1
        for entry in answer.answers:
            if not 1 <= entry.requirement <= len(batch):
                continue  # not a requirement of this batch
            item = batch[entry.requirement - 1]
            if item.index not in outcome.judgments:  # the first answer wins
                outcome.judgments[item.index] = verify_answer(entry, normalized, language)

    for batch in batches:
        await ask(batch)

    unanswered = [item for item in queue if item.index not in outcome.judgments]
    if unanswered:
        retries = build_batches(unanswered, settings.max_requirements_per_call)
        if outcome.llm_calls + len(retries) > settings.max_llm_calls:
            raise JudgeIncompleteError("The judge left requirements unanswered")
        for batch in retries:
            await ask(batch)
        if any(item.index not in outcome.judgments for item in queue):
            raise JudgeIncompleteError("The judge left requirements unanswered")

    logger.info(
        "judge finished",
        extra={
            "llm_calls": outcome.llm_calls,
            "requirements": len(queue),
            "dropped_quotes": outcome.dropped_quotes,
            "downgraded": outcome.downgraded,
            "batches": math.ceil(len(queue) / settings.max_requirements_per_call),
        },
    )
    return outcome
