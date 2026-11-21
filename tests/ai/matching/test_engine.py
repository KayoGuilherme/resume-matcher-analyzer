import logging
import uuid
from datetime import UTC, datetime

import pytest

from app.ai.llm.fake import FakeLLMClient
from app.ai.matching.engine import analyze, check_invariants
from app.ai.matching.errors import AnalysisInvariantError, EmbeddingModelMismatchError
from app.ai.matching.models import (
    AnalysisInput,
    AnalysisSettings,
    Evidence,
    JudgeAnswer,
    JudgeBatch,
    RequirementFinding,
)
from tests.ai.matching.builders import (
    chunk,
    exp,
    job_input,
    kw,
    profile,
    req,
    resume_input,
    stack,
)

NOW = datetime(2026, 1, 15, tzinfo=UTC)
SETTINGS = AnalysisSettings(
    top_k=5, min_similarity=0.4, max_requirements_per_call=8, max_llm_calls=10
)

PYTHON = "Built REST APIs in Python for the billing team"
KUBE = "Deployed a local Kubernetes cluster for demos"
RESUME_TEXT = f"EXPERIENCE\n{PYTHON}\n{KUBE}\nSKILLS\nPython, SQL\n"

A = (1.0, 0.0, 0.0)  # python bullet
B = (0.0, 1.0, 0.0)  # kubernetes bullet
C = (0.0, 0.0, 1.0)  # similar to nothing in the resume


def resume(**kwargs):  # type: ignore[no-untyped-def]
    return resume_input(
        RESUME_TEXT,
        chunks=[chunk(PYTHON, 0, A), chunk(KUBE, 1, B)],
        experiences=[exp(PYTHON, KUBE, start="2020-01", end="2022-12")],
        **kwargs,
    )


def judge_answers(*answers: JudgeAnswer) -> JudgeBatch:
    return JudgeBatch(answers=list(answers))


def answer(n: int, verdict: str, *quotes: str) -> JudgeAnswer:
    return JudgeAnswer.model_validate(
        {"requirement": n, "verdict": verdict, "quotes": list(quotes), "explanation": "Judged."}
    )


async def run(job, facts=None, llm=None, resume_data=None):  # type: ignore[no-untyped-def]
    llm = llm or FakeLLMClient()
    inputs = AnalysisInput(resume=resume_data or resume(), job=job, profile=facts or profile())
    return await analyze(inputs, llm, SETTINGS, NOW), llm


async def test_one_finding_per_requirement_in_job_order() -> None:
    job = job_input(
        req("Rust", keywords=[kw("Rust")], vector=C),
        req("Python", keywords=[kw("Python")], vector=A),
        req("SQL", keywords=[kw("SQL")], vector=A),
    )

    result, _ = await run(job)

    assert [f.requirement_text for f in result.findings] == ["Rust", "Python", "SQL"]


async def test_a_job_without_requirements_gives_an_empty_result_and_no_llm_call() -> None:
    result, llm = await run(job_input(ats_keywords=["python"]))

    assert result.findings == [] and llm.calls == [] and result.provenance.llm_calls == 0
    assert [f.keyword for f in result.ats_coverage.found] == ["python"]


async def test_each_step_decides_its_own_requirement() -> None:
    python = req("Python", keywords=[kw("Python")], vector=A)
    rust = req("Rust", keywords=[kw("Rust")], vector=C)
    orchestration = req("Container orchestration", keywords=[], vector=B)
    docker = req("Docker", keywords=[kw("Docker")], vector=B)
    terraform = req("Terraform", keywords=[kw("Terraform")], vector=C)
    llm = FakeLLMClient(
        [
            judge_answers(
                answer(1, "partial", KUBE),
                answer(2, "met", "Operated Docker swarms for the whole company"),  # invented
            )
        ]
    )

    result, llm = await run(
        job_input(python, rust, orchestration, docker, terraform),
        facts=profile(stacks=[stack("Docker", 3), stack("Terraform", 2)]),
        llm=llm,
    )

    by_text = {f.requirement_text: f for f in result.findings}
    assert (by_text["Python"].verdict, by_text["Python"].decided_by) == ("met", "deterministic")
    assert (by_text["Rust"].verdict, by_text["Rust"].decided_by) == ("missing", "semantic")
    assert (
        by_text["Container orchestration"].verdict,
        by_text["Container orchestration"].decided_by,
    ) == ("partial", "judge")
    assert (by_text["Docker"].verdict, by_text["Docker"].decided_by) == (
        "in_profile_not_in_resume",
        "profile",
    )
    assert (by_text["Terraform"].verdict, by_text["Terraform"].decided_by) == (
        "in_profile_not_in_resume",
        "profile",
    )
    assert len(llm.calls) == 1 and result.provenance.llm_calls == 1


async def test_a_judge_met_with_an_invented_quote_then_the_profile_gives_in_profile() -> None:
    docker = req("Docker", keywords=[kw("Docker")], vector=B)
    llm = FakeLLMClient([judge_answers(answer(1, "met", "Operated Docker swarms at scale"))])

    result, _ = await run(job_input(docker), facts=profile(stacks=[stack("Docker", 3)]), llm=llm)

    (finding,) = result.findings
    assert finding.verdict == "in_profile_not_in_resume" and finding.decided_by == "profile"
    assert finding.flags == ["evidence_not_verbatim"]
    assert all(e.source == "profile" for e in finding.evidence)
    assert {w.code: w.count for w in result.warnings} == {
        "dropped_unverified_evidence": 1,
        "verdicts_downgraded_to_missing": 1,
    }


async def test_the_judge_rule_alone_leaves_missing_when_the_profile_has_nothing() -> None:
    docker = req("Docker", keywords=[kw("Docker")], vector=B)
    llm = FakeLLMClient([judge_answers(answer(1, "met", "Operated Docker swarms at scale"))])

    result, _ = await run(job_input(docker), llm=llm)

    (finding,) = result.findings
    assert (finding.verdict, finding.decided_by, finding.evidence) == ("missing", "judge", [])


async def test_priority_and_unclear_flag_are_copied_unchanged() -> None:
    nice = req("Rust", priority="nice_to_have", keywords=[kw("Rust")], vector=C)
    unclear = req("Go", priority="must_have", priority_unclear=True, keywords=[kw("Go")], vector=C)

    result, _ = await run(job_input(nice, unclear))

    assert [(f.priority, f.priority_unclear) for f in result.findings] == [
        ("nice_to_have", False),
        ("must_have", True),
    ]


async def test_nothing_to_judge_means_no_llm_call_and_the_coverage_is_still_there() -> None:
    job = job_input(
        req("Python", keywords=[kw("Python")], vector=A),
        req("Rust", keywords=[kw("Rust")], vector=C),
        ats_keywords=["python", "terraform"],
    )

    result, llm = await run(job)

    assert llm.calls == []
    assert [f.keyword for f in result.ats_coverage.found] == ["python"]
    assert result.ats_coverage.missing == ["terraform"]


async def test_the_provenance_records_what_produced_the_result() -> None:
    result, _ = await run(job_input(req("Python", keywords=[kw("Python")], vector=A)))

    provenance = result.provenance
    assert (provenance.prompt_name, provenance.prompt_version) == ("gap_judge", 1)
    assert (provenance.llm_provider, provenance.llm_model) == ("fake", "fake-model")
    assert provenance.embedding_model == "fake-embed" and provenance.analyzed_at == NOW
    assert (provenance.top_k, provenance.min_similarity) == (5, 0.4)
    assert (provenance.max_requirements_per_call, provenance.max_llm_calls) == (8, 10)


async def test_different_embedding_models_fail_the_analysis() -> None:
    job = job_input(req("Python", vector=A), embedding_model="other-model")

    with pytest.raises(EmbeddingModelMismatchError):
        await run(job)


async def test_the_engine_does_not_log_resume_job_or_profile_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm = FakeLLMClient([judge_answers(answer(1, "partial", KUBE))])
    job = job_input(
        req("Container orchestration at scale", keywords=[], vector=B),
        req("Python", keywords=[kw("Python")], vector=A),
    )

    with caplog.at_level(logging.DEBUG):
        await run(job, facts=profile(facts=["Secret profile fact"]), llm=llm)

    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for secret in (PYTHON, KUBE, "Container orchestration", "Secret profile fact", "Judged."):
        assert secret not in text


# --- the final pass ---------------------------------------------------------------------------


def _finding(verdict: str, evidence: list[Evidence], explanation: str = "x") -> RequirementFinding:
    return RequirementFinding(
        requirement_id=uuid.uuid4(),
        requirement_text="t",
        category="skill",
        priority="must_have",
        priority_unclear=False,
        verdict=verdict,  # type: ignore[arg-type]
        decided_by="judge",
        evidence=evidence,
        explanation=explanation,
        flags=[],
    )


def _resume_quote(text: str) -> Evidence:
    return Evidence(source="resume", quote=text)


@pytest.mark.parametrize(
    "finding",
    [
        _finding("met", []),
        _finding("met", [_resume_quote("Never written in the resume")]),
        _finding("partial", []),
        _finding("met", [_resume_quote(PYTHON)] * 4),
        _finding("met", [Evidence(source="profile", quote="python: 5 years, expert")]),
        _finding("in_profile_not_in_resume", []),
        _finding("in_profile_not_in_resume", [_resume_quote(PYTHON)]),
        _finding("missing", [_resume_quote(PYTHON)]),
        _finding("missing", [], explanation="  "),
    ],
)
def test_the_final_pass_rejects_a_finding_that_breaks_the_evidence_rule(
    finding: RequirementFinding,
) -> None:
    with pytest.raises(AnalysisInvariantError):
        check_invariants([finding], RESUME_TEXT)


def test_the_final_pass_accepts_well_formed_findings() -> None:
    check_invariants(
        [
            _finding("met", [_resume_quote(PYTHON)]),
            _finding("partial", [_resume_quote(KUBE), _resume_quote(PYTHON)]),
            _finding("in_profile_not_in_resume", [Evidence(source="profile", quote="x")]),
            _finding(
                "in_profile_not_in_resume",
                [_resume_quote(PYTHON), Evidence(source="profile", quote="x")],
            ),
            _finding("missing", []),
        ],
        RESUME_TEXT,
    )
