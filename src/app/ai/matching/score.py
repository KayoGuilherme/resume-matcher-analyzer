"""The score: a weighted coverage of the analysis minus penalties for parsing problems.

Pure arithmetic over a finished `AnalysisResult` and the resume's parsing issues: no LLM, no
database, deterministic. A `met` earns the whole credit, a `partial` the configured fraction, and
`missing` and `in_profile_not_in_resume` nothing: a screener reads only the resume, so what only
the profile proves earns nothing (the report's actions are where that gap is shown).
"""

from collections.abc import Sequence

from app.ai.extraction.job_models import Priority
from app.ai.matching.models import AnalysisResult, RequirementFinding
from app.ai.matching.report_models import (
    CoverageName,
    Outcome,
    Score,
    ScoreCoverage,
    ScorePenalty,
    ScoreSettings,
)
from app.ai.parsing.models import ParsingIssue

_PRIORITY_COVERAGE: dict[Priority, CoverageName] = {
    "must_have": "must_have",
    "nice_to_have": "nice_to_have",
}
_COVERAGE_ORDER: tuple[CoverageName, ...] = ("must_have", "nice_to_have", "keywords")


def _credit(finding: RequirementFinding, settings: ScoreSettings) -> float:
    if finding.verdict == "met":
        return 1.0
    if finding.verdict == "partial":
        return settings.partial_credit
    return 0.0


def _weight(name: CoverageName, settings: ScoreSettings) -> float:
    return {
        "must_have": settings.weight_must_have,
        "nice_to_have": settings.weight_nice_to_have,
        "keywords": settings.weight_keywords,
    }[name]


def _coverages(result: AnalysisResult, settings: ScoreSettings) -> list[ScoreCoverage]:
    credits: dict[CoverageName, list[float]] = {"must_have": [], "nice_to_have": []}
    for finding in result.findings:
        credits[_PRIORITY_COVERAGE[finding.priority]].append(_credit(finding, settings))
    found = len(result.ats_coverage.found)
    keyword_total = found + len(result.ats_coverage.missing)

    values: dict[CoverageName, float | None] = {
        "must_have": _mean(credits["must_have"]),
        "nice_to_have": _mean(credits["nice_to_have"]),
        "keywords": found / keyword_total if keyword_total else None,
    }
    return [
        ScoreCoverage(
            name=name,
            value=None if values[name] is None else round(values[name] or 0.0, 4),
            weight=_weight(name, settings),
            included=values[name] is not None,
        )
        for name in _COVERAGE_ORDER
    ]


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def outcome_for(value: float, settings: ScoreSettings) -> Outcome:
    """The better outcome when the score is exactly on a threshold."""
    if value >= settings.pass_threshold:
        return "likely_pass"
    if value >= settings.borderline_threshold:
        return "borderline"
    return "likely_reject"


def compute_score(
    result: AnalysisResult, issues: Sequence[ParsingIssue], settings: ScoreSettings
) -> Score:
    coverages = _coverages(result, settings)
    penalties = [
        ScorePenalty(
            code=issue.code, severity=issue.severity, points=settings.penalty(issue.severity)
        )
        for issue in issues
    ]
    total_penalty = sum(penalty.points for penalty in penalties)

    counted = [c for c in coverages if c.included and c.value is not None]
    total_weight = sum(c.weight for c in counted)
    if not counted or total_weight <= 0:
        return Score(
            value=None,
            outcome=None,
            measured=False,
            weighted_coverage=None,
            coverages=coverages,
            penalties=penalties,
            total_penalty=total_penalty,
            pass_threshold=settings.pass_threshold,
            borderline_threshold=settings.borderline_threshold,
        )

    weighted = 100 * sum(c.weight * (c.value or 0.0) for c in counted) / total_weight
    value = round(max(0.0, min(100.0, weighted - total_penalty)), 1)
    return Score(
        value=value,
        outcome=outcome_for(value, settings),
        measured=True,
        weighted_coverage=round(weighted, 1),
        coverages=coverages,
        penalties=penalties,
        total_penalty=total_penalty,
        pass_threshold=settings.pass_threshold,
        borderline_threshold=settings.borderline_threshold,
    )
