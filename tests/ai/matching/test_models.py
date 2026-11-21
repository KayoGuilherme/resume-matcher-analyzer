import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.ai.extraction.models import ExtractionWarning
from app.ai.matching.models import (
    AnalysisResult,
    AtsCoverage,
    Evidence,
    FoundKeyword,
    JudgeAnswer,
    JudgeBatch,
    Provenance,
    RequirementFinding,
)


def _finding(**overrides: object) -> RequirementFinding:
    values: dict[str, object] = {
        "requirement_id": uuid.uuid4(),
        "requirement_text": "Python",
        "category": "skill",
        "priority": "must_have",
        "priority_unclear": False,
        "verdict": "met",
        "decided_by": "deterministic",
        "evidence": [Evidence(source="resume", quote="Built APIs in Python")],
        "explanation": "Found.",
        "flags": [],
    }
    values.update(overrides)
    return RequirementFinding.model_validate(values)


def _result() -> AnalysisResult:
    return AnalysisResult(
        findings=[_finding()],
        ats_coverage=AtsCoverage(
            found=[FoundKeyword(keyword="python", matched_text="Python")], missing=["terraform"]
        ),
        warnings=[ExtractionWarning(code="dropped_unverified_evidence", count=1)],
        provenance=Provenance(
            prompt_name="gap_judge",
            prompt_version=1,
            llm_provider="fake",
            llm_model="fake-model",
            embedding_model="fake-embed",
            llm_calls=0,
            top_k=5,
            min_similarity=0.4,
            max_requirements_per_call=8,
            max_llm_calls=10,
            analyzed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )


def test_a_result_round_trips_through_json() -> None:
    result = _result()

    restored = AnalysisResult.model_validate(result.model_dump(mode="json"))

    assert restored == result


@pytest.mark.parametrize("verdict", ["ok", "unknown", "MET", ""])
def test_unknown_verdicts_are_rejected(verdict: str) -> None:
    with pytest.raises(ValidationError):
        _finding(verdict=verdict)


@pytest.mark.parametrize("decided_by", ["llm", "judge ", ""])
def test_unknown_deciding_steps_are_rejected(decided_by: str) -> None:
    with pytest.raises(ValidationError):
        _finding(decided_by=decided_by)


def test_unknown_evidence_sources_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate({"source": "linkedin", "quote": "x"})


def test_the_judge_cannot_answer_with_the_system_only_verdict() -> None:
    with pytest.raises(ValidationError):
        JudgeAnswer.model_validate(
            {
                "requirement": 1,
                "verdict": "in_profile_not_in_resume",
                "quotes": [],
                "explanation": "x",
            }
        )


def test_the_llm_schema_has_no_ids_score_or_deciding_step() -> None:
    fields = set(JudgeAnswer.model_fields) | set(JudgeBatch.model_fields)

    assert fields == {"requirement", "verdict", "quotes", "explanation", "answers"}


def test_every_field_of_the_llm_schema_is_required() -> None:
    assert all(field.is_required() for field in JudgeAnswer.model_fields.values())
    assert all(field.is_required() for field in JudgeBatch.model_fields.values())


def test_the_result_has_no_score() -> None:
    names = set(AnalysisResult.model_fields) | set(AtsCoverage.model_fields)

    assert not any("score" in name or "percent" in name or "ratio" in name for name in names)
