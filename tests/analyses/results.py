"""A small valid `AnalysisResult` for the tests that store or return one."""

from datetime import UTC, datetime

from app.ai.matching.models import AnalysisResult, AtsCoverage, Provenance


def a_result(llm_calls: int = 0) -> AnalysisResult:
    return AnalysisResult(
        findings=[],
        ats_coverage=AtsCoverage(found=[], missing=[]),
        warnings=[],
        provenance=Provenance(
            prompt_name="gap_judge",
            prompt_version=1,
            llm_provider="fake",
            llm_model="fake-model",
            embedding_model="fake-embed",
            llm_calls=llm_calls,
            top_k=5,
            min_similarity=0.4,
            max_requirements_per_call=8,
            max_llm_calls=10,
            analyzed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
