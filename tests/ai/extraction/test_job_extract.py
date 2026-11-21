import logging
from datetime import UTC, datetime

import pytest

from app.ai.extraction.job import build_posting_text, extract_job
from app.ai.extraction.job_models import ExtractedJob
from app.ai.llm.base import LLMInvalidOutputError
from app.ai.llm.fake import FakeLLMClient
from tests.ai.extraction.job_builders import job, keyword, requirement

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)

POSTING = """\
Backend Engineer

Requirements:
- 3+ years of Java
- Strong knowledge of Python is required
- Experience with Docker and
  Kubernetes

Nice to have:
- Experience with Terraform
"""
JAVA = "3+ years of Java"
PYTHON = "Strong knowledge of Python is required"
DOCKER = "Experience with Docker and Kubernetes"
TERRAFORM = "Experience with Terraform"


def _llm(*answers: ExtractedJob | str | Exception) -> FakeLLMClient:
    return FakeLLMClient(list(answers), provider="fake-provider", model="fake-model-1")


async def test_requirements_are_found_in_the_description_or_the_requirements_text() -> None:
    posting = build_posting_text("About the role. Backend work.", "- 3+ years of Java\n- Go")
    llm = _llm(job(requirement(JAVA, min_years=3), requirement("Go")))

    result = await extract_job(llm, posting, NOW)

    assert [r.source_text for r in result.job.requirements] == [JAVA, "Go"]


async def test_a_complete_extraction_decides_priorities_from_the_posting() -> None:
    answer = job(
        requirement(
            JAVA, text="Java", min_years=3, priority="must_have", keywords=[keyword("Java")]
        ),
        requirement(PYTHON, text="Python", priority="nice_to_have"),
        requirement(DOCKER, text="Docker and Kubernetes", priority="unclear"),
        requirement(TERRAFORM, text="Terraform", priority="must_have"),
        seniority="mid",
        responsibilities=[],
        ats_keywords=["Java", "Python", "Docker", "K8s"],
    )
    llm = _llm(answer)

    result = await extract_job(llm, POSTING, NOW)

    java, python, docker, terraform = result.job.requirements
    assert (java.priority, java.priority_unclear, java.min_years) == ("must_have", False, 3)
    assert (python.priority, python.priority_unclear) == ("must_have", False)  # own cue "required"
    assert (docker.priority, docker.priority_unclear) == ("must_have", False)  # under Requirements
    assert (terraform.priority, terraform.priority_unclear) == ("nice_to_have", False)  # heading
    assert result.job.seniority == "mid" and result.job.language == "en"
    assert result.job.ats_keywords == ["java", "python", "docker", "kubernetes"]
    assert result.warnings == []
    assert len(llm.calls) == 1
    assert len({r.id for r in result.job.requirements}) == 4


async def test_the_model_cannot_override_a_cue_in_the_posting() -> None:
    posting = "Experience with Go is a plus\n"
    answer = job(requirement("Experience with Go is a plus", text="Go", priority="must_have"))

    result = await extract_job(_llm(answer), posting, NOW)

    assert result.job.requirements[0].priority == "nice_to_have"


async def test_unclear_priorities_are_flagged_and_counted() -> None:
    posting = "About you:\n- Redis\n- Kafka\n- Postgres\n"
    answer = job(
        requirement("Redis", priority="unclear"),
        requirement("Kafka", priority="nice_to_have"),
        requirement("Postgres", priority="unclear"),
    )

    result = await extract_job(_llm(answer), posting, NOW)

    redis, kafka, postgres = result.job.requirements
    assert [(r.priority, r.priority_unclear) for r in (redis, kafka, postgres)] == [
        ("must_have", True),
        ("nice_to_have", False),
        ("must_have", True),
    ]
    assert [(w.code, w.count) for w in result.warnings] == [("priority_unclear_requirements", 2)]


async def test_an_invented_requirement_is_corrected_on_the_second_call() -> None:
    first = job(requirement(JAVA), requirement("Five years of Rust"))
    second = job(requirement(JAVA), requirement(TERRAFORM))
    llm = _llm(first, second)

    result = await extract_job(llm, POSTING, NOW)

    assert [r.source_text for r in result.job.requirements] == [JAVA, TERRAFORM]
    assert result.warnings == []
    assert len(llm.calls) == 2
    assert "Five years of Rust" in llm.calls[1].prompt
    assert "Five years of Rust" not in llm.calls[0].prompt


async def test_an_invented_requirement_that_persists_is_dropped_and_counted() -> None:
    answer = job(requirement(JAVA), requirement("Five years of Rust"))

    result = await extract_job(_llm(answer, answer), POSTING, NOW)

    assert [r.source_text for r in result.job.requirements] == [JAVA]
    assert [(w.code, w.count) for w in result.warnings] == [("dropped_unverified_items", 1)]


async def test_a_reworded_source_text_is_dropped() -> None:
    answer = job(requirement("Java experience of at least three years"))

    result = await extract_job(_llm(answer, answer), POSTING, NOW)

    assert result.job.requirements == []
    assert [(w.code, w.count) for w in result.warnings] == [("dropped_unverified_items", 1)]


async def test_a_source_text_with_different_line_breaks_is_kept() -> None:
    answer = job(requirement(DOCKER))  # the posting wraps it over two lines

    llm = _llm(answer)
    result = await extract_job(llm, POSTING, NOW)

    assert len(result.job.requirements) == 1
    assert len(llm.calls) == 1


async def test_an_invented_responsibility_is_dropped_and_a_real_one_kept() -> None:
    posting = "You will design APIs.\nYou will mentor juniors.\n"
    answer = job(responsibilities=["You will design APIs.", "You will manage the budget."])

    result = await extract_job(_llm(answer, answer), posting, NOW)

    assert result.job.responsibilities == ["You will design APIs."]
    assert [(w.code, w.count) for w in result.warnings] == [("dropped_unverified_items", 1)]


async def test_duplicates_are_kept_once_but_a_split_sentence_keeps_both() -> None:
    posting = "Python and Go are required\n"
    answer = job(
        requirement("Python and Go are required", text="Python"),
        requirement("Python and Go are required", text="Go"),
        requirement("Python and Go are required", text="python"),
    )

    result = await extract_job(_llm(answer), posting, NOW)

    assert [r.text for r in result.job.requirements] == ["Python", "Go"]


async def test_keywords_are_normalized_in_the_result() -> None:
    posting = "Postgres is required\nPortuguês fluente obrigatório\n"
    answer = job(
        requirement("Postgres is required", keywords=[keyword("Postgres", "PostgreSQL")]),
        requirement(
            "Português fluente obrigatório", category="language", keywords=[keyword("Português")]
        ),
    )

    result = await extract_job(_llm(answer), posting, NOW)

    pg, pt = result.job.requirements
    assert (pg.keywords[0].name, pg.keywords[0].normalized, pg.keywords[0].synonyms) == (
        "Postgres",
        "postgresql",
        [],
    )
    assert pt.keywords[0].normalized == "portuguese"


async def test_other_languages_and_missing_seniority_and_no_requirements_are_accepted() -> None:
    result = await extract_job(_llm(job(language="other")), "Some posting", NOW)

    assert result.job.language == "other"
    assert result.job.seniority is None
    assert result.job.requirements == []
    assert result.warnings == []


async def test_provenance_is_recorded() -> None:
    result = await extract_job(_llm(job()), "Some posting", NOW)

    assert result.prompt_name == "job_extraction"
    assert result.prompt_version >= 1
    assert (result.llm_provider, result.llm_model) == ("fake-provider", "fake-model-1")
    assert result.extracted_at == NOW


async def test_the_prompt_carries_the_posting_in_delimiters_and_the_system_rules() -> None:
    llm = _llm(job())

    await extract_job(llm, POSTING, NOW)

    (call,) = llm.calls
    assert "<posting>" in call.prompt and POSTING in call.prompt
    assert call.system is not None and "DATA" in call.system
    assert call.schema is ExtractedJob


async def test_unusable_output_propagates_and_nothing_is_returned() -> None:
    with pytest.raises(LLMInvalidOutputError):
        await extract_job(_llm(LLMInvalidOutputError("bad")), POSTING, NOW)


async def test_logs_have_counts_and_no_posting_text(caplog: pytest.LogCaptureFixture) -> None:
    answer = job(requirement(JAVA), requirement("Invented requirement about Rust"))
    llm = _llm(answer, answer)

    with caplog.at_level(logging.DEBUG):
        await extract_job(llm, POSTING, NOW)

    (record,) = [r for r in caplog.records if r.name == "app.ai.extraction.job"]
    assert record.__dict__["dropped_items"] == 1
    assert record.__dict__["correction_round"] is True
    logged = " ".join(str(r.__dict__) + r.getMessage() for r in caplog.records)
    for fragment in ("Java", "Terraform", "Backend Engineer", "Rust"):
        assert fragment not in logged
