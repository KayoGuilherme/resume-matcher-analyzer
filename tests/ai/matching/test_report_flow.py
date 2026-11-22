from datetime import UTC, datetime

import pytest

from app.ai.llm.base import LLMTransientError
from app.ai.llm.fake import FakeLLMClient
from app.ai.matching.engine import analyze
from app.ai.matching.models import AnalysisSettings, JudgeBatch
from app.ai.matching.report import missing_keywords, produce_report
from app.ai.matching.report_models import (
    ReportSettings,
    ScreenerAnswer,
    SuggestionAnswer,
    SuggestionBatch,
)
from tests.fixtures.analysis_cases import Case, english, portuguese

NOW = datetime(2026, 1, 15, tzinfo=UTC)
ANALYSIS = AnalysisSettings(
    top_k=5, min_similarity=0.4, max_requirements_per_call=8, max_llm_calls=10
)
REPORT = ReportSettings(screener_runs=3, max_suggestions=8)


def screening(decision: str = "borderline") -> ScreenerAnswer:
    return ScreenerAnswer.model_validate({"decision": decision, "reasons": ["Mixed."]})


def suggestions(*answers: SuggestionAnswer) -> SuggestionBatch:
    return SuggestionBatch(suggestions=list(answers))


async def analysed(case: Case, extra: list[object], settings: ReportSettings = REPORT):  # type: ignore[no-untyped-def]
    llm = FakeLLMClient([*case.judge_calls, *extra])  # type: ignore[arg-type]
    result = await analyze(case.inputs, llm, ANALYSIS, NOW)
    return llm, result


async def test_the_screener_runs_then_one_suggestion_call() -> None:
    case = english()
    honest = SuggestionAnswer(
        target=2, source="profile", number=1, text="Ran services on AWS for three years"
    )
    llm, result = await analysed(
        case,
        [screening("borderline"), screening("pass"), screening("borderline"), suggestions(honest)],
    )

    stored = await produce_report(case.inputs, result, [], llm, REPORT, NOW)

    assert [call.schema for call in llm.calls] == [
        JudgeBatch,
        ScreenerAnswer,
        ScreenerAnswer,
        ScreenerAnswer,
        SuggestionBatch,
    ]
    assert stored.screener.decision == "borderline" and stored.screener.consistency == 0.67
    assert [s.text for s in stored.suggestions.accepted] == [honest.text]
    assert stored.suggestions.accepted[0].based_on.text == "aws, 3 years (working)"
    assert stored.provenance.llm_calls == 4
    assert stored.provenance.screener_prompt_name == "screener"
    assert stored.provenance.suggestions_prompt_name == "rewrite_suggestions"
    assert stored.provenance.llm_provider == "fake" and stored.language == "en"
    assert stored.provenance.generated_at == NOW and stored.provenance.max_suggestions == 8


async def test_the_suggestion_targets_are_the_profile_findings_then_the_partial_ones() -> None:
    case = english()
    llm, result = await analysed(case, [screening()] * 3 + [suggestions()])

    await produce_report(case.inputs, result, [], llm, REPORT, NOW)

    prompt = llm.calls[-1].prompt
    assert "[T1] requirement (must_have): Fluent English" in prompt
    assert "[T2] requirement (must_have): AWS" in prompt
    assert "[T3] requirement (must_have): 5+ years of backend development" in prompt
    assert "[T4]" not in prompt
    assert "[P1] aws, 3 years (working)" in prompt and "[P3] english (C1)" in prompt


async def test_the_report_calls_are_not_made_when_there_is_nothing_to_suggest() -> None:
    case = english()
    llm, result = await analysed(case, [screening()] * 3 + [suggestions()])

    stored = await produce_report(
        case.inputs, result, [], llm, ReportSettings(screener_runs=3, max_suggestions=0), NOW
    )

    assert llm.calls[-1].schema is ScreenerAnswer
    assert stored.provenance.llm_calls == 3 and stored.suggestions.accepted == []


async def test_a_screener_failure_propagates() -> None:
    case = english()
    llm, result = await analysed(case, [screening(), LLMTransientError("down")])

    with pytest.raises(LLMTransientError):
        await produce_report(case.inputs, result, [], llm, REPORT, NOW)


async def test_a_suggestion_failure_propagates() -> None:
    case = english()
    llm, result = await analysed(case, [screening()] * 3 + [LLMTransientError("down")])

    with pytest.raises(LLMTransientError):
        await produce_report(case.inputs, result, [], llm, REPORT, NOW)


async def test_invented_suggestions_are_rejected_and_counted() -> None:
    case = english()
    invented = [
        SuggestionAnswer(target=2, source="profile", number=1, text="Ran AWS Lambda at scale"),
        SuggestionAnswer(target=3, source="resume", number=1, text="Built REST APIs for 9 years"),
    ]
    llm, result = await analysed(case, [screening()] * 3 + [suggestions(*invented)])

    stored = await produce_report(case.inputs, result, [], llm, REPORT, NOW)

    assert stored.suggestions.accepted == []
    assert {w.code: w.count for w in stored.suggestions.rejected} == {
        "unsupported_technology": 1,
        "unsupported_number": 1,
    }


async def test_the_issues_are_snapshotted() -> None:
    from tests.ai.matching.report_builders import issue

    case = english()
    llm, result = await analysed(case, [screening()] * 3 + [suggestions()])

    stored = await produce_report(case.inputs, result, [issue()], llm, REPORT, NOW)

    assert [i.code for i in stored.issues] == ["tables"]


async def test_the_missing_keywords_know_the_profile_and_the_requirements() -> None:
    case = english()
    _, result = await analysed(case, [])

    keywords = missing_keywords(result, case.inputs.job, case.inputs.profile)

    assert [k.keyword for k in keywords] == ["terraform", "kafka"]
    assert [k.in_profile for k in keywords] == [False, False]
    terraform = next(f for f in result.findings if f.requirement_text == "Terraform")
    kafka = next(f for f in result.findings if f.requirement_text.startswith("Message queues"))
    assert keywords[0].requirement_ids == [terraform.requirement_id]
    assert keywords[1].requirement_ids == [kafka.requirement_id]


async def test_a_profile_stack_among_the_missing_keywords_is_marked() -> None:
    case = portuguese()
    _, result = await analysed(case, [])

    keywords = missing_keywords(result, case.inputs.job, case.inputs.profile)

    stacks = {s.name for s in case.inputs.profile.stacks}
    assert all(k.in_profile == (k.keyword in stacks) for k in keywords)


async def test_a_portuguese_job_gets_a_portuguese_language_in_the_stored_report() -> None:
    case = portuguese()
    llm, result = await analysed(case, [screening()] * 3 + [suggestions()])

    stored = await produce_report(case.inputs, result, [], llm, REPORT, NOW)

    assert stored.language == "pt"
    assert "in Portuguese" in llm.calls[-4].prompt
