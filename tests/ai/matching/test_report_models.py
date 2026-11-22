import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.ai.matching.models import AtsCoverage
from app.ai.matching.report_models import (
    Action,
    MissingKeyword,
    Report,
    ReportProvenance,
    Score,
    ScoreCoverage,
    ScoreSettings,
    ScreenerAnswer,
    ScreenerReport,
    ScreenerResult,
    ScreenerRun,
    StoredReport,
    Suggestion,
    SuggestionBasis,
    SuggestionBatch,
    SuggestionSet,
    SuggestionTarget,
)
from app.ai.parsing.models import ParsingIssue


def _provenance() -> ReportProvenance:
    return ReportProvenance(
        screener_prompt_name="screener",
        screener_prompt_version=1,
        suggestions_prompt_name="rewrite_suggestions",
        suggestions_prompt_version=1,
        llm_provider="fake",
        llm_model="fake-model",
        llm_calls=4,
        screener_runs=3,
        max_suggestions=8,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _stored() -> StoredReport:
    return StoredReport(
        language="en",
        screener=ScreenerResult(
            decision="pass",
            consistency=0.67,
            runs=[ScreenerRun(decision="pass", reasons=["Shows the must-haves."])],
        ),
        suggestions=SuggestionSet(
            accepted=[
                Suggestion(
                    id="S1",
                    target=SuggestionTarget(kind="keyword", requirement_id=None, text="docker"),
                    original=None,
                    text="Shipped services in Docker containers",
                    based_on=SuggestionBasis(source="profile", text="Docker, 3 years"),
                )
            ],
            rejected=[],
        ),
        missing_keywords=[MissingKeyword(keyword="docker", in_profile=True, requirement_ids=[])],
        issues=[ParsingIssue(code="tables", severity="warning", message="Tables.")],
        provenance=_provenance(),
    )


def _settings() -> ScoreSettings:
    return ScoreSettings(
        weight_must_have=0.6,
        weight_nice_to_have=0.15,
        weight_keywords=0.25,
        partial_credit=0.5,
        penalty_critical=40,
        penalty_warning=5,
        penalty_info=1,
        pass_threshold=70,
        borderline_threshold=50,
    )


def test_a_stored_report_round_trips_through_json() -> None:
    stored = _stored()

    assert StoredReport.model_validate_json(stored.model_dump_json()) == stored


def test_a_report_round_trips_through_json() -> None:
    stored = _stored()
    report = Report(
        analysis_id=uuid.uuid4(),
        resume_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        language="en",
        disclaimer="A simulation.",
        score=Score(
            value=67.5,
            outcome="borderline",
            measured=True,
            weighted_coverage=72.5,
            coverages=[ScoreCoverage(name="must_have", value=0.75, weight=0.6, included=True)],
            penalties=[],
            total_penalty=5,
            pass_threshold=70,
            borderline_threshold=50,
        ),
        score_settings=_settings(),
        screener=ScreenerReport(**stored.screener.model_dump(), agrees_with_score=False),
        ats_coverage=AtsCoverage(found=[], missing=["docker"]),
        actions=[Action(priority=1, kind="fix_format", text="Fix it.", issue_code="tables")],
        suggestions=stored.suggestions.accepted,
        warnings=[],
        provenance=stored.provenance,
    )

    assert Report.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (ScreenerRun, {"decision": "maybe", "reasons": []}),
        (Action, {"priority": 1, "kind": "nice", "text": "x"}),
        (Score, {"outcome": "great"}),
        (Suggestion, {"id": "S1"}),
    ],
)
def test_unknown_values_are_rejected(model: type, data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_unknown_suggestion_sources_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SuggestionBasis(source="web", text="x")  # type: ignore[arg-type]


def test_the_penalty_follows_the_severity() -> None:
    settings = _settings()

    assert [settings.penalty(s) for s in ("critical", "warning", "info")] == [40, 5, 1]


def test_the_llm_schemas_have_no_id_score_or_outcome_field() -> None:
    forbidden = {"id", "score", "outcome", "value", "agrees_with_score"}
    for schema in (ScreenerAnswer, SuggestionBatch):
        text = str(schema.model_json_schema())
        assert not any(f"'{name}':" in text for name in forbidden), schema.__name__


def test_every_llm_schema_field_is_required() -> None:
    for schema in (ScreenerAnswer, SuggestionBatch):
        properties = schema.model_json_schema()["properties"]
        assert set(schema.model_json_schema()["required"]) == set(properties)
