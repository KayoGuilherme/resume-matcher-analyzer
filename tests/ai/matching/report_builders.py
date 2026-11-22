"""Builders for the report tests: findings, results, settings and issues."""

import uuid
from datetime import UTC, datetime

from app.ai.extraction.models import ExtractionWarning
from app.ai.matching.models import (
    AnalysisResult,
    AtsCoverage,
    Evidence,
    FoundKeyword,
    Provenance,
    RequirementFinding,
)
from app.ai.matching.report_models import (
    MissingKeyword,
    ReportProvenance,
    ScoreSettings,
    ScreenerResult,
    ScreenerRun,
    StoredReport,
    Suggestion,
    SuggestionBasis,
    SuggestionSet,
    SuggestionTarget,
)
from app.ai.matching.screener import majority
from app.ai.parsing.models import ParsingIssue


def finding(
    verdict: str,
    *,
    text: str = "Python",
    priority: str = "must_have",
    priority_unclear: bool = False,
    decided_by: str | None = None,
) -> RequirementFinding:
    evidence: list[Evidence] = []
    if verdict in ("met", "partial"):
        evidence = [Evidence(source="resume", quote=f"Worked with {text}")]
    elif verdict == "in_profile_not_in_resume":
        evidence = [Evidence(source="profile", quote=f"{text}, 3 years")]
    return RequirementFinding.model_validate(
        {
            "requirement_id": uuid.uuid4(),
            "requirement_text": text,
            "category": "skill",
            "priority": priority,
            "priority_unclear": priority_unclear,
            "verdict": verdict,
            "decided_by": decided_by or ("profile" if verdict.startswith("in_") else "judge"),
            "evidence": evidence,
            "explanation": "Because.",
            "flags": [],
        }
    )


def result(
    findings: list[RequirementFinding],
    *,
    found: list[str] | None = None,
    missing: list[str] | None = None,
) -> AnalysisResult:
    return AnalysisResult(
        findings=findings,
        ats_coverage=AtsCoverage(
            found=[FoundKeyword(keyword=k, matched_text=k) for k in found or []],
            missing=missing or [],
        ),
        warnings=[],
        provenance=Provenance(
            prompt_name="gap_judge",
            prompt_version=1,
            llm_provider="fake",
            llm_model="fake-model",
            embedding_model="fake-embed",
            llm_calls=1,
            top_k=5,
            min_similarity=0.4,
            max_requirements_per_call=8,
            max_llm_calls=10,
            analyzed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )


def score_settings(**overrides: float) -> ScoreSettings:
    values: dict[str, float] = {
        "weight_must_have": 0.6,
        "weight_nice_to_have": 0.15,
        "weight_keywords": 0.25,
        "partial_credit": 0.5,
        "penalty_critical": 40,
        "penalty_warning": 5,
        "penalty_info": 1,
        "pass_threshold": 70,
        "borderline_threshold": 50,
    }
    values.update(overrides)
    return ScoreSettings.model_validate(values)


def issue(code: str = "tables", severity: str = "warning") -> ParsingIssue:
    return ParsingIssue.model_validate(
        {"code": code, "severity": severity, "message": f"About {code}."}
    )


def suggestion(
    id: str = "S1",
    *,
    requirement_id: uuid.UUID | None = None,
    keyword: str | None = None,
    text: str = "Shipped services in Docker containers",
    original: str | None = None,
) -> Suggestion:
    return Suggestion(
        id=id,
        target=SuggestionTarget(
            kind="requirement" if requirement_id else "keyword",
            requirement_id=requirement_id,
            text=keyword or "target",
        ),
        original=original,
        text=text,
        based_on=SuggestionBasis(source="profile", text="docker, 2 years (working)"),
    )


def stored_report(
    *,
    language: str = "en",
    issues: list[ParsingIssue] | None = None,
    missing_keywords: list[MissingKeyword] | None = None,
    suggestions: list[Suggestion] | None = None,
    rejected: list[ExtractionWarning] | None = None,
    decisions: tuple[str, ...] = ("pass", "pass", "pass"),
) -> StoredReport:
    runs = [ScreenerRun.model_validate({"decision": d, "reasons": ["Reason."]}) for d in decisions]
    decision, consistency = majority([run.decision for run in runs])
    return StoredReport.model_validate(
        {
            "language": language,
            "screener": ScreenerResult(decision=decision, consistency=consistency, runs=runs),
            "suggestions": SuggestionSet(accepted=suggestions or [], rejected=rejected or []),
            "missing_keywords": missing_keywords or [],
            "issues": issues or [],
            "provenance": ReportProvenance(
                screener_prompt_name="screener",
                screener_prompt_version=1,
                suggestions_prompt_name="rewrite_suggestions",
                suggestions_prompt_version=1,
                llm_provider="fake",
                llm_model="fake-model",
                llm_calls=len(runs) + 1,
                screener_runs=len(runs),
                max_suggestions=8,
                generated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        }
    )
