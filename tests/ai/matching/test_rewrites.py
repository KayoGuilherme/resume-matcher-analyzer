import logging
import uuid

import pytest

from app.ai.llm.base import LLMTransientError
from app.ai.llm.fake import FakeLLMClient
from app.ai.matching.report_models import MissingKeyword, SuggestionAnswer, SuggestionBatch
from app.ai.matching.rewrites import (
    Target,
    build_corpus,
    build_vocabulary,
    resume_bullets,
    select_targets,
    suggest,
)
from tests.ai.matching.builders import exp, profile, resume_input, stack
from tests.ai.matching.report_builders import finding, result

BULLETS = [
    "Built REST APIs in Python and FastAPI",
    "Cut query time by 60% on PostgreSQL",
    "Maintained the billing service",
    "Deployed services on K8s",
]
RESUME_TEXT = "Jane Doe\nExperience\n" + "\n".join(BULLETS)
FACTS = profile(
    total_years=5,
    stacks=[stack("Python", 3), stack("Docker", 2), stack("Kubernetes", 2)],
    facts=["Won a hackathon in 2022"],
)
RESUME = resume_input(RESUME_TEXT, experiences=[exp(*BULLETS)]).resume


def keyword(name: str, in_profile: bool = True, *ids: uuid.UUID) -> MissingKeyword:
    return MissingKeyword(keyword=name, in_profile=in_profile, requirement_ids=list(ids))


def answer(target: int, source: str, number: int, text: str) -> SuggestionAnswer:
    return SuggestionAnswer.model_validate(
        {"target": target, "source": source, "number": number, "text": text}
    )


def run_suggest(llm: FakeLLMClient, targets: list[Target], facts=FACTS, resume=RESUME):  # type: ignore[no-untyped-def]
    corpus = build_corpus(RESUME_TEXT, facts)
    vocabulary = build_vocabulary(
        job_keywords=[], ats_keywords=[], resume_names=["Python"], profile=facts
    )
    return suggest(targets, resume, facts, corpus, vocabulary, llm)


# --- targets ----------------------------------------------------------------------------------


def test_targets_are_profile_findings_then_partial_ones_then_keywords() -> None:
    nice_profile = finding("in_profile_not_in_resume", text="Docker", priority="nice_to_have")
    must_profile = finding("in_profile_not_in_resume", text="Kubernetes")
    partial = finding("partial", text="Python 5 years")
    missing = finding("missing", text="Rust")
    analysis = result([nice_profile, partial, missing, must_profile])

    targets = select_targets(analysis, [keyword("terraform")], 10)

    assert [(t.kind, t.text) for t in targets] == [
        ("requirement", "Kubernetes"),
        ("requirement", "Docker"),
        ("requirement", "Python 5 years"),
        ("keyword", "terraform"),
    ]
    assert targets[0].requirement_id == must_profile.requirement_id
    assert targets[0].priority == "must_have"


def test_a_must_have_partial_comes_before_a_nice_to_have_partial() -> None:
    analysis = result(
        [
            finding("partial", text="nice", priority="nice_to_have"),
            finding("partial", text="must"),
        ]
    )

    assert [t.text for t in select_targets(analysis, [], 10)] == ["must", "nice"]


def test_only_profile_stacks_are_keyword_targets() -> None:
    targets = select_targets(result([]), [keyword("docker"), keyword("rust", False)], 10)

    assert [t.text for t in targets] == ["docker"]


def test_a_keyword_of_a_targeted_requirement_is_not_a_second_target() -> None:
    kube = finding("in_profile_not_in_resume", text="Kubernetes")

    targets = select_targets(
        result([kube]),
        [keyword("kubernetes", True, kube.requirement_id), keyword("docker")],
        10,
    )

    assert [t.text for t in targets] == ["Kubernetes", "docker"]


def test_a_keyword_of_a_requirement_that_is_not_a_target_stays_a_target() -> None:
    other = finding("missing", text="Docker")

    targets = select_targets(result([other]), [keyword("docker", True, other.requirement_id)], 10)

    assert [t.text for t in targets] == ["docker"]


def test_the_cap_limits_the_targets() -> None:
    findings = [finding("in_profile_not_in_resume", text=f"R{n}") for n in range(12)]

    assert len(select_targets(result(findings), [], 8)) == 8
    assert select_targets(result(findings), [], 0) == []


def test_missing_and_met_requirements_are_not_targets() -> None:
    analysis = result([finding("missing"), finding("met")])

    assert select_targets(analysis, [], 10) == []


async def test_twelve_targets_with_a_cap_of_eight_ask_for_eight_in_one_call() -> None:
    findings = [finding("in_profile_not_in_resume", text=f"Req {n}") for n in range(12)]
    targets = select_targets(result(findings), [], 8)
    llm = FakeLLMClient([SuggestionBatch(suggestions=[])])

    suggestions, calls = await run_suggest(llm, targets)

    assert calls == 1 and len(llm.calls) == 1
    assert "[T8]" in llm.calls[0].prompt and "[T9]" not in llm.calls[0].prompt
    assert suggestions.accepted == []


async def test_no_target_makes_no_call() -> None:
    llm = FakeLLMClient()

    suggestions, calls = await run_suggest(llm, [])

    assert calls == 0 and llm.calls == []
    assert suggestions.accepted == [] and suggestions.rejected == []


# --- resolving and checking -------------------------------------------------------------------

TARGETS = [Target("requirement", "Kubernetes in production", uuid.uuid4(), "must_have")]


def test_resume_bullets_are_the_experience_bullets_in_order() -> None:
    assert resume_bullets(RESUME) == BULLETS


async def test_a_resume_source_is_resolved_to_the_exact_bullet() -> None:
    text = "Deployed services on Kubernetes"
    llm = FakeLLMClient([SuggestionBatch(suggestions=[answer(1, "resume", 4, text)])])

    suggestions, _ = await run_suggest(llm, TARGETS)

    [accepted] = suggestions.accepted
    assert accepted.id == "S1"
    assert accepted.original == BULLETS[3] == accepted.based_on.text
    assert accepted.based_on.source == "resume"
    assert accepted.text == text
    assert accepted.target.kind == "requirement"
    assert accepted.target.requirement_id == TARGETS[0].requirement_id


async def test_a_profile_stack_source_gives_a_new_bullet_made_of_its_values() -> None:
    text = "Ran containerized services on Docker"
    llm = FakeLLMClient([SuggestionBatch(suggestions=[answer(1, "profile", 2, text)])])

    suggestions, _ = await run_suggest(llm, TARGETS)

    [accepted] = suggestions.accepted
    assert accepted.original is None
    assert accepted.based_on.source == "profile"
    assert accepted.based_on.text == "docker, 2 years (working)"


async def test_a_notable_fact_is_pointed_to_as_written() -> None:
    text = "Won a hackathon in 2022 with a Python prototype"
    llm = FakeLLMClient([SuggestionBatch(suggestions=[answer(1, "profile", 4, text)])])

    suggestions, _ = await run_suggest(llm, TARGETS)

    assert suggestions.accepted[0].based_on.text == "Won a hackathon in 2022"


@pytest.mark.parametrize(
    ("target", "source", "number"),
    [(1, "resume", 99), (1, "resume", 0), (1, "profile", 99), (7, "resume", 1)],
)
async def test_an_unknown_source_or_target_is_rejected(
    target: int, source: str, number: int
) -> None:
    llm = FakeLLMClient(
        [SuggestionBatch(suggestions=[answer(target, source, number, "Something new")])]
    )

    suggestions, _ = await run_suggest(llm, TARGETS)

    assert suggestions.accepted == []
    assert [(w.code, w.count) for w in suggestions.rejected] == [("unknown_source", 1)]


async def test_inventions_are_rejected_and_counted_and_honest_ones_kept() -> None:
    targets = [Target("keyword", name) for name in ("docker", "kafka", "latency", "python")]
    batch = SuggestionBatch(
        suggestions=[
            answer(1, "profile", 2, "Containerized services with Docker"),
            answer(2, "resume", 4, "Streamed events with Kafka"),
            answer(3, "resume", 2, "Cut latency by 90% on PostgreSQL"),
            answer(4, "profile", 1, "Led 8 engineers using Python and Kafka"),
        ]
    )
    llm = FakeLLMClient([batch])

    suggestions, _ = await run_suggest(llm, targets)

    assert [s.text for s in suggestions.accepted] == ["Containerized services with Docker"]
    counts = {w.code: w.count for w in suggestions.rejected}
    assert counts == {"unsupported_technology": 2, "unsupported_number": 2}


async def test_rejected_text_appears_nowhere_in_the_returned_set() -> None:
    llm = FakeLLMClient(
        [SuggestionBatch(suggestions=[answer(1, "resume", 4, "Zorbify the 99% Kafka pipeline")])]
    )

    suggestions, _ = await run_suggest(llm, TARGETS)

    dumped = suggestions.model_dump_json()
    assert "Zorbify" not in dumped and "Kafka" not in dumped and "99" not in dumped
    assert suggestions.accepted == []


async def test_one_suggestion_is_kept_per_target() -> None:
    batch = SuggestionBatch(
        suggestions=[
            answer(1, "resume", 4, "Deployed services on Kubernetes"),
            answer(1, "profile", 3, "Ran Kubernetes clusters for two years"),
        ]
    )
    llm = FakeLLMClient([batch])

    suggestions, _ = await run_suggest(llm, TARGETS)

    assert len(suggestions.accepted) == 1


async def test_a_second_answer_is_used_when_the_first_is_rejected() -> None:
    batch = SuggestionBatch(
        suggestions=[
            answer(1, "resume", 4, "Deployed services on Kafka"),
            answer(1, "resume", 4, "Deployed services on Kubernetes"),
        ]
    )
    llm = FakeLLMClient([batch])

    suggestions, _ = await run_suggest(llm, TARGETS)

    assert [s.text for s in suggestions.accepted] == ["Deployed services on Kubernetes"]


async def test_ids_follow_the_accepted_order() -> None:
    targets = [Target("keyword", "docker"), Target("keyword", "kubernetes")]
    batch = SuggestionBatch(
        suggestions=[
            answer(1, "profile", 2, "Containerized services with Docker"),
            answer(2, "resume", 4, "Deployed services on Kubernetes"),
        ]
    )
    llm = FakeLLMClient([batch])

    suggestions, _ = await run_suggest(llm, targets)

    assert [s.id for s in suggestions.accepted] == ["S1", "S2"]


async def test_the_prompt_lists_targets_bullets_and_profile_items_by_number() -> None:
    llm = FakeLLMClient([SuggestionBatch(suggestions=[])])

    await run_suggest(llm, [*TARGETS, Target("keyword", "docker")])

    prompt = llm.calls[0].prompt
    assert "[T1] requirement (must_have): Kubernetes in production" in prompt
    assert "[T2] keyword: docker" in prompt
    assert f"[B4] {BULLETS[3]}" in prompt
    assert "[P2] docker, 2 years (working)" in prompt
    assert "[P4] Won a hackathon in 2022" in prompt


async def test_portuguese_bullets_go_to_a_prompt_that_asks_for_their_language() -> None:
    bullets = ["Desenvolvi APIs REST em Python", "Reduzi o tempo de consulta em 60%"]
    resume = resume_input("\n".join(bullets), experiences=[exp(*bullets)]).resume
    llm = FakeLLMClient([SuggestionBatch(suggestions=[])])
    corpus = build_corpus("\n".join(bullets), FACTS)

    await suggest(TARGETS, resume, FACTS, corpus, [], llm)

    assert "Desenvolvi APIs REST em Python" in llm.calls[0].prompt
    assert "language of the bullet" in (llm.calls[0].system or "")


async def test_an_llm_failure_propagates() -> None:
    llm = FakeLLMClient([LLMTransientError("down")])

    with pytest.raises(LLMTransientError):
        await run_suggest(llm, TARGETS)


async def test_no_log_record_contains_a_suggestion_a_bullet_or_a_profile_fact(
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm = FakeLLMClient(
        [
            SuggestionBatch(
                suggestions=[
                    answer(1, "resume", 4, "Deployed services on Kubernetes"),
                    answer(1, "resume", 2, "Invented Kafka work"),
                ]
            )
        ]
    )

    with caplog.at_level(logging.DEBUG):
        await run_suggest(llm, TARGETS)

    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "suggestions finished" in logged
    for secret in ("Kubernetes", "Kafka", "hackathon", "billing", "K8s"):
        assert secret not in logged
