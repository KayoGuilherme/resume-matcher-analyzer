from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from app.ai.extraction.verify import is_verbatim, normalize
from app.ai.llm.fake import FakeLLMClient
from app.ai.matching.engine import analyze
from app.ai.matching.messages import explain
from app.ai.matching.models import AnalysisResult, AnalysisSettings
from tests.fixtures.analysis_cases import Case, english, portuguese

NOW = datetime(2026, 1, 15, tzinfo=UTC)
SETTINGS = AnalysisSettings(
    top_k=5, min_similarity=0.4, max_requirements_per_call=8, max_llm_calls=10
)
CASES: list[Callable[[], Case]] = [english, portuguese]


async def _run(case: Case) -> tuple[AnalysisResult, FakeLLMClient]:
    llm = FakeLLMClient(list(case.judge_calls))
    return await analyze(case.inputs, llm, SETTINGS, NOW), llm


@pytest.mark.parametrize("build", CASES, ids=["english", "portuguese"])
async def test_the_findings_equal_the_expected_list_exactly(build: Callable[[], Case]) -> None:
    case = build()

    result, llm = await _run(case)

    actual = [
        (
            f.requirement_text,
            f.verdict,
            f.decided_by,
            tuple((e.source, e.quote) for e in f.evidence),
            tuple(f.flags),
        )
        for f in result.findings
    ]
    assert actual == case.expected
    assert len(llm.calls) == len(case.judge_calls)


@pytest.mark.parametrize("build", CASES, ids=["english", "portuguese"])
async def test_the_ats_coverage_and_the_warnings_equal_the_expectation(
    build: Callable[[], Case],
) -> None:
    case = build()

    result, _ = await _run(case)

    assert [(f.keyword, f.matched_text) for f in result.ats_coverage.found] == case.found
    assert result.ats_coverage.missing == case.missing
    assert {w.code: w.count for w in result.warnings} == case.warnings


@pytest.mark.parametrize("build", CASES, ids=["english", "portuguese"])
async def test_every_resume_quote_of_the_output_is_in_the_resume_text(
    build: Callable[[], Case],
) -> None:
    case = build()

    result, _ = await _run(case)

    normalized = normalize(case.inputs.resume.text)
    quotes = [e.quote for f in result.findings for e in f.evidence if e.source == "resume"]
    assert quotes and all(is_verbatim(quote, normalized) for quote in quotes)


@pytest.mark.parametrize("build", CASES, ids=["english", "portuguese"])
async def test_the_system_explanations_are_in_the_language_of_the_job(
    build: Callable[[], Case],
) -> None:
    case = build()

    result, _ = await _run(case)

    semantic = next(f for f in result.findings if f.decided_by == "semantic")
    assert semantic.explanation == explain("no_similar_content", case.language)
    assert all(f.explanation.strip() for f in result.findings)


@pytest.mark.parametrize("build", CASES, ids=["english", "portuguese"])
async def test_the_result_does_not_depend_on_running_it_twice(build: Callable[[], Case]) -> None:
    first, _ = await _run(build())
    second, _ = await _run(build())

    def view(result: AnalysisResult) -> list[tuple[str, str, str]]:
        return [(f.requirement_text, f.verdict, f.decided_by) for f in result.findings]

    assert view(first) == view(second)
