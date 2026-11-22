import uuid

import pytest

from app.ai.extraction.job_models import JobRequirement
from app.ai.matching.models import Evidence
from app.ai.matching.rewrites import build_corpus, build_vocabulary
from evals.config import EvalSettings
from evals.dataset import ExpectedRequirement
from evals.metrics import (
    AMBIGUOUS,
    NO_MATCH,
    CaseResult,
    Check,
    Fabrication,
    Metrics,
    RunRecord,
    checks_for,
    fabrication,
    gate,
    match_expected,
    summarize,
    wrong_requirements,
)
from tests.ai.matching.builders import kw, profile, req
from tests.ai.matching.report_builders import finding, suggestion


def requirement(text: str, *keywords: str) -> JobRequirement:
    return req(text, keywords=[kw(k) for k in keywords]).requirement


def expected(match: str, verdict: str = "met") -> ExpectedRequirement:
    return ExpectedRequirement.model_validate({"match": match, "verdict": verdict})


def run(
    verdicts: list[str | None],
    *,
    outcome: str | None = "borderline",
    expected_verdicts: list[str] | None = None,
    consistency: float = 1.0,
    bad: int = 0,
    checked: int = 4,
    kept: int = 10,
    dropped: int = 0,
) -> RunRecord:
    wanted = expected_verdicts or ["met"] * len(verdicts)
    checks = [
        Check(f"r{n}", w, v, None) for n, (w, v) in enumerate(zip(wanted, verdicts, strict=True))
    ]
    return RunRecord(
        checks=checks,
        outcome=outcome,  # type: ignore[arg-type]
        screener_decision="pass",
        screener_consistency=consistency,
        fabrication=Fabrication(bad, checked),
        quotes_kept=kept,
        quotes_dropped=dropped,
    )


def case(runs: list[RunRecord], outcome: str = "borderline", case_id: str = "en-01") -> CaseResult:
    return CaseResult(case_id, outcome, runs)  # type: ignore[arg-type]


# --- matching ---------------------------------------------------------------------------------


def test_an_expectation_matches_the_requirement_by_text_or_keyword_folded() -> None:
    kube = requirement("Container orchestration", "Kubernetes")
    english = requirement("Inglês avançado", "English")

    matched = match_expected([expected("KUBERNETES"), expected("ingles")], [kube, english])

    assert [m.requirement_id for m in matched] == [kube.id, english.id]
    assert all(m.reason is None for m in matched)


def test_an_expectation_that_matches_nothing_is_reported() -> None:
    [matched] = match_expected([expected("rust")], [requirement("Python", "Python")])

    assert matched.requirement_id is None and matched.reason == NO_MATCH


def test_an_expectation_that_matches_two_requirements_is_reported() -> None:
    first, second = requirement("Python services"), requirement("Python scripts")

    [matched] = match_expected([expected("python")], [first, second])

    assert matched.requirement_id is None and matched.reason == AMBIGUOUS


def test_checks_hold_the_actual_verdict_or_the_reason() -> None:
    a, b = requirement("Python"), requirement("Rust")
    matched = match_expected(
        [expected("python"), expected("rust", "missing"), expected("go")], [a, b]
    )

    checks = checks_for(matched, {a.id: "met", b.id: "partial"})

    assert [(c.actual, c.correct, c.reason) for c in checks] == [
        ("met", True, None),
        ("partial", False, None),
        (None, False, NO_MATCH),
    ]


def test_a_matched_requirement_without_a_verdict_is_wrong() -> None:
    a = requirement("Python")

    [check] = checks_for(match_expected([expected("python")], [a]), {})

    assert not check.correct and check.reason == "no verdict"


# --- the metrics ------------------------------------------------------------------------------


def test_seventeen_of_twenty_is_zero_point_eight_five() -> None:
    right = run(["met"] * 17 + [None] * 3, expected_verdicts=["met"] * 20)

    assert summarize([case([right])]).verdict_accuracy == pytest.approx(0.85)


def test_accuracy_counts_every_run() -> None:
    good = run(["met", "met"])
    half = run(["met", "missing"])

    assert summarize([case([good, half])]).verdict_accuracy == 0.75


def test_outcome_accuracy_is_over_case_runs() -> None:
    runs = [run(["met"], outcome="borderline"), run(["met"], outcome="likely_pass")]

    assert summarize([case(runs, "borderline")]).outcome_accuracy == 0.5


def test_a_run_without_an_outcome_is_not_correct() -> None:
    assert summarize([case([run(["met"], outcome=None)])]).outcome_accuracy == 0


def test_verdicts_met_met_partial_give_a_consistency_of_two_thirds() -> None:
    runs = [run(["met"]), run(["met"]), run(["partial"])]

    assert summarize([case(runs)]).consistency == pytest.approx(2 / 3)


def test_consistency_is_averaged_over_the_expected_requirements() -> None:
    runs = [run(["met", "met"]), run(["met", "partial"])]

    assert summarize([case(runs)]).consistency == pytest.approx(0.75)


def test_outcome_and_screener_consistency_are_reported() -> None:
    runs = [
        run(["met"], outcome="borderline", consistency=1.0),
        run(["met"], outcome="borderline", consistency=0.67),
        run(["met"], outcome="likely_pass", consistency=1.0),
    ]

    metrics = summarize([case(runs)])

    assert metrics.outcome_consistency == pytest.approx(2 / 3)
    assert metrics.screener_consistency == pytest.approx((1 + 0.67 + 1) / 3)


def test_the_dropped_quote_share_is_informational() -> None:
    metrics = summarize([case([run(["met"], kept=9, dropped=1)])])

    assert metrics.dropped_quote_share == pytest.approx(0.1)
    assert summarize([case([run(["met"], kept=0, dropped=0)])]).dropped_quote_share == 0


def test_the_fabricated_rate_sums_the_runs() -> None:
    metrics = summarize([case([run(["met"], bad=1, checked=4), run(["met"], bad=0, checked=4)])])

    assert metrics.fabricated_rate == 0.125 and (metrics.fabricated, metrics.checked) == (1, 8)
    assert summarize([case([run(["met"], bad=0, checked=0)])]).fabricated_rate == 0


# --- fabrication ------------------------------------------------------------------------------

RESUME = "Experience\nBuilt REST APIs in Python and FastAPI\nCut query time by 60%"
FACTS = profile(total_years=5)


def test_a_resume_quote_that_is_not_in_the_text_is_fabricated() -> None:
    good = finding("met")
    bad = finding("met").model_copy(
        update={"evidence": [Evidence(source="resume", quote="Led a team of nine at Google")]}
    )

    result = fabrication(
        [
            good.model_copy(
                update={"evidence": [Evidence(source="resume", quote="Built REST APIs in Python")]}
            ),
            bad,
        ],
        RESUME,
        [],
        build_corpus(RESUME, FACTS),
        [],
    )

    assert (result.fabricated, result.checked) == (1, 2) and result.rate == 0.5


def test_profile_evidence_is_not_checked_against_the_resume() -> None:
    profile_finding = finding("in_profile_not_in_resume")

    result = fabrication([profile_finding], RESUME, [], build_corpus(RESUME, FACTS), [])

    assert (result.fabricated, result.checked) == (0, 0) and result.rate == 0


def test_an_accepted_suggestion_with_an_invented_number_is_fabricated() -> None:
    corpus = build_corpus(RESUME, FACTS)
    vocabulary = build_vocabulary(job_keywords=[], ats_keywords=[], resume_names=[], profile=FACTS)
    honest = suggestion("S1", text="Cut query time by 60% with Python", original=None)
    invented = suggestion("S2", text="Cut query time by 80% with Python", original=None)

    result = fabrication([], RESUME, [honest, invented], corpus, vocabulary)

    assert (result.fabricated, result.checked) == (1, 2)


# --- the gate ---------------------------------------------------------------------------------


def metrics(**changes: float) -> Metrics:
    values = {
        "verdict_accuracy": 0.85,
        "outcome_accuracy": 0.8,
        "fabricated_rate": 0.0,
        "dropped_quote_share": 0.0,
        "consistency": 0.95,
        "outcome_consistency": 1.0,
        "screener_consistency": 1.0,
    }
    values.update(changes)
    return Metrics(**values)


def test_the_gate_passes_when_every_metric_meets_its_threshold() -> None:
    assert gate(metrics(), EvalSettings()) == []


def test_the_gate_names_the_metric_its_value_and_its_threshold() -> None:
    [failure] = gate(metrics(verdict_accuracy=0.7), EvalSettings())

    assert (failure.metric, failure.value, failure.threshold) == ("verdict accuracy", 0.7, 0.8)


def test_any_fabricated_evidence_fails_with_everything_else_passing() -> None:
    [failure] = gate(metrics(fabricated_rate=0.001), EvalSettings())

    assert failure.metric == "fabricated-evidence rate" and failure.threshold == 0


@pytest.mark.parametrize(
    ("field", "value", "name"),
    [
        ("outcome_accuracy", 0.5, "outcome accuracy"),
        ("consistency", 0.5, "consistency"),
    ],
)
def test_each_threshold_fails_on_its_own(field: str, value: float, name: str) -> None:
    [failure] = gate(metrics(**{field: value}), EvalSettings())

    assert failure.metric == name


def test_a_value_exactly_on_its_threshold_passes() -> None:
    assert gate(metrics(verdict_accuracy=0.8, consistency=0.9), EvalSettings()) == []


# --- the per-case report ----------------------------------------------------------------------


def test_wrong_requirements_list_what_was_expected_and_seen() -> None:
    runs = [
        run(["met", "partial"], expected_verdicts=["met", "met"]),
        run(["met", "missing"], expected_verdicts=["met", "met"]),
    ]

    [wrong] = wrong_requirements(case(runs))

    assert (wrong.match, wrong.expected, wrong.actual) == ("r1", "met", ["partial", "missing"])


def test_no_wrong_requirement_when_every_run_is_right() -> None:
    assert wrong_requirements(case([run(["met"]), run(["met"])])) == []


def test_an_unmatched_expectation_is_listed_with_its_reason() -> None:
    record = RunRecord(
        checks=[Check("rust", "missing", None, NO_MATCH)],
        outcome="borderline",
        screener_decision="pass",
        screener_consistency=1.0,
        fabrication=Fabrication(0, 0),
        quotes_kept=0,
        quotes_dropped=0,
    )

    [wrong] = wrong_requirements(case([record]))

    assert wrong.actual == ["none"] and wrong.reason == NO_MATCH
    assert uuid  # keeps the import used in type-only helpers
