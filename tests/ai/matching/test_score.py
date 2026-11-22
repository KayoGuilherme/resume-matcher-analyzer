import pytest

from app.ai.matching.score import compute_score, outcome_for
from tests.ai.matching.report_builders import finding, issue, result, score_settings

SETTINGS = score_settings()


def _worked_example():
    findings = [finding("met", text=f"m{i}") for i in range(3)] + [finding("missing", text="m3")]
    findings += [
        finding("met", text="n0", priority="nice_to_have"),
        finding("missing", text="n1", priority="nice_to_have"),
    ]
    found = [f"k{i}" for i in range(8)]
    return result(findings, found=found, missing=["k8", "k9"])


def test_the_worked_example_with_one_warning() -> None:
    score = compute_score(_worked_example(), [issue()], SETTINGS)

    assert score.weighted_coverage == 72.5
    assert score.total_penalty == 5
    assert score.value == 67.5
    assert score.outcome == "borderline"
    assert score.measured


def test_a_partial_earns_the_configured_credit() -> None:
    analysis = result([finding("partial")], found=["a"])

    score = compute_score(analysis, [], score_settings(weight_keywords=0, weight_nice_to_have=0))

    must = next(c for c in score.coverages if c.name == "must_have")
    assert must.value == 0.5
    assert score.value == 50


@pytest.mark.parametrize("verdict", ["missing", "in_profile_not_in_resume"])
def test_missing_and_profile_only_earn_nothing(verdict: str) -> None:
    score = compute_score(result([finding(verdict)]), [], SETTINGS)

    assert next(c for c in score.coverages if c.name == "must_have").value == 0
    assert score.value == 0


def test_a_profile_only_requirement_scores_exactly_like_a_missing_one() -> None:
    profile_only = compute_score(result([finding("in_profile_not_in_resume")]), [], SETTINGS)
    missing = compute_score(result([finding("missing")]), [], SETTINGS)

    assert profile_only.value == missing.value


def test_a_coverage_with_nothing_to_measure_is_left_out() -> None:
    findings = [finding("met", text=f"m{i}") for i in range(3)] + [finding("missing", text="m3")]
    analysis = result(findings, found=[f"k{i}" for i in range(8)], missing=["k8", "k9"])

    score = compute_score(analysis, [], SETTINGS)

    nice = next(c for c in score.coverages if c.name == "nice_to_have")
    assert nice.value is None and not nice.included
    assert score.value == 76.5


def test_penalties_larger_than_the_coverage_give_zero() -> None:
    analysis = result([finding("missing")], missing=["a"])

    assert compute_score(analysis, [issue("x", "critical")], SETTINGS).value == 0


def test_a_perfect_resume_gives_one_hundred() -> None:
    analysis = result([finding("met")], found=["a"])

    assert compute_score(analysis, [], SETTINGS).value == 100


def test_a_perfect_resume_with_penalties_is_below_one_hundred() -> None:
    analysis = result([finding("met")], found=["a"])

    assert compute_score(analysis, [issue("x", "info")], SETTINGS).value == 99


def test_nothing_to_measure_gives_no_score_and_no_outcome() -> None:
    score = compute_score(result([]), [issue()], SETTINGS)

    assert score.value is None and score.outcome is None
    assert not score.measured
    assert score.total_penalty == 5
    assert all(not c.included for c in score.coverages)


def test_only_zero_weighted_coverages_means_nothing_could_be_measured() -> None:
    settings = score_settings(weight_must_have=0, weight_nice_to_have=0)

    score = compute_score(result([finding("met")]), [], settings)

    assert score.value is None and not score.measured


def test_an_unclear_priority_follows_the_reported_priority() -> None:
    analysis = result(
        [finding("met", priority="nice_to_have", priority_unclear=True), finding("missing")]
    )

    score = compute_score(analysis, [], SETTINGS)

    values = {c.name: c.value for c in score.coverages}
    assert values["nice_to_have"] == 1 and values["must_have"] == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (85, "likely_pass"),
        (67.5, "borderline"),
        (49.9, "likely_reject"),
        (70, "likely_pass"),
        (50, "borderline"),
        (0, "likely_reject"),
    ],
)
def test_the_outcome_comes_from_the_thresholds(value: float, expected: str) -> None:
    assert outcome_for(value, SETTINGS) == expected


def test_custom_weights_are_scaled_to_add_up_to_one() -> None:
    analysis = result([finding("met"), finding("met", priority="nice_to_have")], missing=["a"])
    settings = score_settings(weight_must_have=1, weight_nice_to_have=1, weight_keywords=2)

    score = compute_score(analysis, [], settings)

    assert score.value == 50  # (1*1 + 1*1 + 2*0) / 4


def test_the_same_input_gives_the_same_score() -> None:
    analysis = _worked_example()

    assert compute_score(analysis, [issue()], SETTINGS) == compute_score(
        analysis, [issue()], SETTINGS
    )


def test_the_breakdown_alone_recomputes_the_score() -> None:
    score = compute_score(_worked_example(), [issue(), issue("y", "critical")], SETTINGS)

    included = [c for c in score.coverages if c.included]
    weighted = (
        100 * sum(c.weight * (c.value or 0) for c in included) / sum(c.weight for c in included)
    )
    recomputed = max(0, min(100, weighted - sum(p.points for p in score.penalties)))

    assert score.value == pytest.approx(recomputed, abs=0.1)
    assert score.pass_threshold == 70 and score.borderline_threshold == 50
