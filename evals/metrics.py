"""The eval metrics, as pure functions over the results of the runs.

Nothing here reads a resume, calls a provider or prints: it takes the verdicts, outcomes and
evidence that the runner collected and turns them into numbers, and compares them with the
thresholds. The fabricated-evidence check re-verifies the final output with the production
functions, independently of the stages' own guards.
"""

import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from app.ai.extraction.job_models import JobRequirement
from app.ai.extraction.verify import is_verbatim, normalize
from app.ai.matching.models import RequirementFinding
from app.ai.matching.report_models import Outcome, Suggestion
from app.ai.matching.rewrites import Corpus, check_suggestion
from app.ai.matching.text import fold
from evals.config import EvalSettings
from evals.dataset import ExpectedRequirement

NO_MATCH = "no requirement matched"
AMBIGUOUS = "more than one requirement matched"
NOT_ANSWERED = "no verdict"


# --- matching the expectations to the extracted requirements ----------------------------------


@dataclass(frozen=True)
class Matched:
    expected: ExpectedRequirement
    requirement_id: uuid.UUID | None  # None when it matched no requirement or more than one
    reason: str | None  # why it did not match


def _names(requirement: JobRequirement) -> list[str]:
    names = [requirement.text]
    for keyword in requirement.keywords:
        names += [keyword.name, keyword.normalized, *keyword.synonyms]
    return [fold(name) for name in names]


def match_expected(
    expected: Sequence[ExpectedRequirement], requirements: Sequence[JobRequirement]
) -> list[Matched]:
    """Match each expectation to the one requirement whose text or keywords contain its folded
    `match`. Zero or several matches are reported, never guessed."""
    matched: list[Matched] = []
    for item in expected:
        needle = fold(item.match)
        hits = [r for r in requirements if any(needle in name for name in _names(r))]
        if len(hits) == 1:
            matched.append(Matched(item, hits[0].id, None))
        else:
            matched.append(Matched(item, None, NO_MATCH if not hits else AMBIGUOUS))
    return matched


# --- what one run produced --------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One expected requirement in one run."""

    match: str
    expected: str
    actual: str | None  # None when the expectation matched no (or several) requirements
    reason: str | None

    @property
    def correct(self) -> bool:
        return self.actual == self.expected


@dataclass(frozen=True)
class Fabrication:
    fabricated: int
    checked: int

    @property
    def rate(self) -> float:
        return self.fabricated / self.checked if self.checked else 0.0


@dataclass(frozen=True)
class RunRecord:
    checks: list[Check]
    outcome: Outcome | None
    screener_decision: str
    screener_consistency: float
    fabrication: Fabrication
    quotes_kept: int  # resume quotes in the final findings
    quotes_dropped: int  # quotes the judge gave that the guard dropped


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    expected_outcome: Outcome
    runs: list[RunRecord]


def checks_for(matched: Sequence[Matched], verdicts: Mapping[uuid.UUID, str]) -> list[Check]:
    checks: list[Check] = []
    for item in matched:
        if item.requirement_id is None:
            checks.append(Check(item.expected.match, item.expected.verdict, None, item.reason))
        else:
            actual = verdicts.get(item.requirement_id)
            reason = None if actual is not None else NOT_ANSWERED
            checks.append(Check(item.expected.match, item.expected.verdict, actual, reason))
    return checks


def fabrication(
    findings: Iterable[RequirementFinding],
    resume_text: str,
    suggestions: Iterable[Suggestion],
    corpus: Corpus,
    vocabulary: Iterable[str],
) -> Fabrication:
    """Resume quotes that are not in the resume text plus suggestions that fail the invention
    check, over all the quotes and suggestions. Verified again here, not trusted."""
    normalized = normalize(resume_text)
    vocabulary = frozenset(vocabulary)
    quotes = [e.quote for f in findings for e in f.evidence if e.source == "resume"]
    bad_quotes = sum(1 for quote in quotes if not is_verbatim(quote, normalized))
    accepted = list(suggestions)
    bad_suggestions = sum(
        1 for s in accepted if check_suggestion(s.text, s.original, corpus, vocabulary)
    )
    return Fabrication(bad_quotes + bad_suggestions, len(quotes) + len(accepted))


# --- the metrics ------------------------------------------------------------------------------


def _share_of_most_frequent(values: Sequence[object]) -> float:
    return max(Counter(values).values()) / len(values)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


@dataclass(frozen=True)
class Metrics:
    verdict_accuracy: float
    outcome_accuracy: float
    fabricated_rate: float
    dropped_quote_share: float  # informational
    consistency: float
    outcome_consistency: float  # informational
    screener_consistency: float  # informational
    fabricated: int = 0
    checked: int = 0


def summarize(results: Sequence[CaseResult]) -> Metrics:
    runs = [(result, run) for result in results for run in result.runs]
    checks = [check for _, run in runs for check in run.checks]
    fabricated = sum(run.fabrication.fabricated for _, run in runs)
    checked = sum(run.fabrication.checked for _, run in runs)
    kept = sum(run.quotes_kept for _, run in runs)
    dropped = sum(run.quotes_dropped for _, run in runs)

    per_requirement: list[float] = []
    per_outcome: list[float] = []
    for result in results:
        for position in range(len(result.runs[0].checks)):
            per_requirement.append(
                _share_of_most_frequent([run.checks[position].actual for run in result.runs])
            )
        per_outcome.append(_share_of_most_frequent([run.outcome for run in result.runs]))

    return Metrics(
        verdict_accuracy=_mean([1.0 if check.correct else 0.0 for check in checks]),
        outcome_accuracy=_mean(
            [1.0 if run.outcome == result.expected_outcome else 0.0 for result, run in runs]
        ),
        fabricated_rate=fabricated / checked if checked else 0.0,
        dropped_quote_share=dropped / (dropped + kept) if dropped + kept else 0.0,
        consistency=_mean(per_requirement),
        outcome_consistency=_mean(per_outcome),
        screener_consistency=_mean([run.screener_consistency for _, run in runs]),
        fabricated=fabricated,
        checked=checked,
    )


@dataclass(frozen=True)
class Failure:
    metric: str
    value: float
    threshold: float
    direction: str  # "below" or "above"


def gate(metrics: Metrics, settings: EvalSettings) -> list[Failure]:
    """The metrics that miss their threshold. Any fabricated evidence fails (threshold 0)."""
    failures: list[Failure] = []
    for name, value, threshold in (
        ("verdict accuracy", metrics.verdict_accuracy, settings.min_verdict_accuracy),
        ("outcome accuracy", metrics.outcome_accuracy, settings.min_outcome_accuracy),
        ("consistency", metrics.consistency, settings.min_consistency),
    ):
        if value < threshold:
            failures.append(Failure(name, value, threshold, "below"))
    if metrics.fabricated_rate > 0:
        failures.append(Failure("fabricated-evidence rate", metrics.fabricated_rate, 0.0, "above"))
    return failures


# --- the per-case report ----------------------------------------------------------------------


@dataclass(frozen=True)
class WrongRequirement:
    match: str
    expected: str
    actual: list[str]  # the distinct verdicts or reasons seen, in the order of the runs
    reason: str | None = field(default=None)


def wrong_requirements(result: CaseResult) -> list[WrongRequirement]:
    """The expected requirements whose verdict was wrong in at least one run."""
    wrong: list[WrongRequirement] = []
    for position, first in enumerate(result.runs[0].checks):
        seen = [run.checks[position] for run in result.runs]
        if all(check.correct for check in seen):
            continue
        actual = list(dict.fromkeys(check.actual or "none" for check in seen))
        reason = next((check.reason for check in seen if check.reason), None)
        wrong.append(WrongRequirement(first.match, first.expected, actual, reason))
    return wrong
