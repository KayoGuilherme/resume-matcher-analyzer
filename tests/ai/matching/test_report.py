import uuid

from app.ai.extraction.models import ExtractionWarning
from app.ai.matching.report import build_report
from app.ai.matching.screener import DISCLAIMERS
from tests.ai.matching.report_builders import (
    finding,
    issue,
    result,
    score_settings,
    stored_report,
    suggestion,
)

IDS = {"analysis_id": uuid.uuid4(), "resume_id": uuid.uuid4(), "job_id": uuid.uuid4()}


def _analysis():  # type: ignore[no-untyped-def]
    profile_finding = finding("in_profile_not_in_resume", text="Docker")
    findings = [
        finding("met", text="Python"),
        finding("met", text="FastAPI"),
        finding("met", text="SQL"),
        finding("missing", text="Rust"),
        profile_finding,
    ]
    return result(findings, found=["python", "sql"], missing=["docker", "rust"]), profile_finding


def _stored(profile_finding):  # type: ignore[no-untyped-def]
    return stored_report(
        issues=[issue("tables", "warning")],
        suggestions=[suggestion("S1", requirement_id=profile_finding.requirement_id)],
        rejected=[ExtractionWarning(code="unsupported_number", count=2)],
    )


def test_the_report_holds_every_part() -> None:
    analysis, profile_finding = _analysis()

    report = build_report(
        **IDS, result=analysis, stored=_stored(profile_finding), score_settings=score_settings()
    )

    assert (report.analysis_id, report.resume_id, report.job_id) == tuple(IDS.values())
    assert report.language == "en"
    assert report.disclaimer == DISCLAIMERS["en"]
    assert report.score.value is not None and report.score.outcome is not None
    assert report.screener.decision == "pass" and report.screener.consistency == 1.0
    assert report.ats_coverage == analysis.ats_coverage
    assert [a.kind for a in report.actions] == ["fix_format", "add_from_profile", "real_gap"]
    assert [s.id for s in report.suggestions] == ["S1"]
    assert report.provenance.llm_calls == 4


def test_the_disclaimer_is_always_present_and_does_not_depend_on_the_screener() -> None:
    analysis, profile_finding = _analysis()

    for decisions in [("pass",) * 3, ("reject",) * 3, ("pass", "reject", "borderline")]:
        stored = stored_report(decisions=decisions)
        report = build_report(
            **IDS, result=analysis, stored=stored, score_settings=score_settings()
        )
        assert report.disclaimer == DISCLAIMERS["en"]


def test_a_portuguese_job_gets_the_portuguese_disclaimer() -> None:
    analysis, _ = _analysis()

    report = build_report(
        **IDS, result=analysis, stored=stored_report(language="pt"), score_settings=score_settings()
    )

    assert report.disclaimer == DISCLAIMERS["pt"]


def test_the_report_states_the_settings_used() -> None:
    analysis, profile_finding = _analysis()
    settings = score_settings(pass_threshold=80, penalty_warning=7)

    report = build_report(
        **IDS, result=analysis, stored=_stored(profile_finding), score_settings=settings
    )

    assert report.score_settings == settings
    assert report.score.pass_threshold == 80
    assert report.score.penalties[0].points == 7


def test_the_same_stored_report_scored_with_two_thresholds_changes_only_the_outcome() -> None:
    analysis, profile_finding = _analysis()
    stored = _stored(profile_finding)
    strict = build_report(**IDS, result=analysis, stored=stored, score_settings=score_settings())
    lenient = build_report(
        **IDS,
        result=analysis,
        stored=stored,
        score_settings=score_settings(pass_threshold=40, borderline_threshold=20),
    )

    assert strict.score.value == lenient.score.value
    assert strict.score.outcome != lenient.score.outcome
    assert lenient.score.outcome == "likely_pass"
    assert strict.screener.runs == lenient.screener.runs
    assert strict.suggestions == lenient.suggestions
    assert strict.actions == lenient.actions


def test_the_screener_agreement_follows_the_score() -> None:
    analysis, profile_finding = _analysis()
    stored = stored_report(decisions=("pass",) * 3)

    agree = build_report(
        **IDS,
        result=analysis,
        stored=stored,
        score_settings=score_settings(pass_threshold=40, borderline_threshold=20),
    )
    differ = build_report(**IDS, result=analysis, stored=stored, score_settings=score_settings())

    assert agree.screener.agrees_with_score is True
    assert differ.screener.agrees_with_score is False


def test_without_a_score_the_agreement_is_unknown() -> None:
    report = build_report(
        **IDS, result=result([]), stored=stored_report(), score_settings=score_settings()
    )

    assert report.score.value is None
    assert report.screener.agrees_with_score is None


def test_rejected_suggestions_are_warnings_by_reason() -> None:
    analysis, profile_finding = _analysis()

    report = build_report(
        **IDS, result=analysis, stored=_stored(profile_finding), score_settings=score_settings()
    )

    assert [(w.code, w.count) for w in report.warnings] == [
        ("suggestion_rejected_unsupported_number", 2)
    ]


def test_the_provenance_names_both_prompts_and_counts_the_calls() -> None:
    analysis, _ = _analysis()

    report = build_report(
        **IDS, result=analysis, stored=stored_report(), score_settings=score_settings()
    )

    provenance = report.provenance
    assert (provenance.screener_prompt_name, provenance.screener_prompt_version) == ("screener", 1)
    assert (provenance.suggestions_prompt_name, provenance.suggestions_prompt_version) == (
        "rewrite_suggestions",
        1,
    )
    assert provenance.llm_calls == 4 and provenance.llm_model == "fake-model"
