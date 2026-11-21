import logging
from datetime import UTC, datetime

import pytest

from app.ai.extraction.models import ExtractedProject, ExtractedResume
from app.ai.extraction.resume import extract_resume
from app.ai.llm.base import LLMInvalidOutputError
from app.ai.llm.fake import FakeLLMClient
from tests.ai.extraction.builders import RESUME_TEXT, experience, extracted

NOW = datetime(2024, 6, 15, 12, 0, tzinfo=UTC)
GOOD = "Reduced p95 latency by 40%"
WRAPPED = "Built a payments API with Spring Boot and PostgreSQL"


def _llm(*answers: ExtractedResume | str | Exception) -> FakeLLMClient:
    return FakeLLMClient(list(answers), provider="fake-provider", model="fake-model-1")


async def test_a_complete_resume_is_extracted_with_provenance() -> None:
    answer = extracted(
        summary="Desenvolvedora backend com foco em APIs.",
        experiences=[experience(WRAPPED, GOOD, start="2020-01", end="2021-12")],
        skills=["Languages: Java, Python, SQL", "Cloud: AWS, Docker"],
        projects=[
            ExtractedProject(
                name="Resume Matcher",
                bullets=["Matches resumes against job posts"],
                technologies=["Python"],
            )
        ],
    )
    llm = _llm(answer)

    result = await extract_resume(llm, RESUME_TEXT, NOW)

    resume = result.resume
    assert resume.summary == "Desenvolvedora backend com foco em APIs."
    assert [line.text for line in resume.skills] == [
        "Languages: Java, Python, SQL",
        "Cloud: AWS, Docker",
    ]
    (job,) = resume.experiences
    assert job.bullets == [WRAPPED, GOOD]
    assert (job.title, job.start, job.end) == ("Backend Developer", "2020-01", "2021-12")
    assert resume.education[0].institution == "USP"
    assert resume.languages[0].name == "Portuguese"
    assert resume.certifications[0].name == "AWS SAA"
    assert resume.projects[0].bullets == ["Matches resumes against job posts"]
    assert len(llm.calls) == 1
    assert result.warnings == []
    assert result.total_experience_months == 24
    assert result.total_experience_years == 2.0
    assert (result.llm_provider, result.llm_model) == ("fake-provider", "fake-model-1")
    assert result.prompt_name == "resume_extraction"
    assert result.prompt_version >= 1
    assert result.extracted_at == NOW


async def test_ids_are_assigned_by_code_and_are_unique() -> None:
    answer = extracted(
        experiences=[experience(GOOD), experience(WRAPPED)],
        projects=[ExtractedProject(name="P", bullets=[], technologies=[])],
    )

    result = await extract_resume(_llm(answer), RESUME_TEXT, NOW)

    ids = [e.id for e in result.resume.experiences] + [p.id for p in result.resume.projects]
    assert len(set(ids)) == 3


async def test_a_resume_without_experience_succeeds() -> None:
    result = await extract_resume(_llm(extracted()), RESUME_TEXT, NOW)

    assert result.resume.experiences == []
    assert (result.total_experience_months, result.warnings) == (0, [])


async def test_the_prompt_carries_the_resume_between_delimiters_and_the_system_rules() -> None:
    llm = _llm(extracted())

    await extract_resume(llm, RESUME_TEXT, NOW)

    (call,) = llm.calls
    assert "<resume>" in call.prompt and RESUME_TEXT in call.prompt
    assert call.system is not None and "DATA" in call.system
    assert call.schema is ExtractedResume


async def test_a_paraphrased_bullet_is_corrected_on_the_second_call() -> None:
    first = extracted(experiences=[experience("Cut p95 latency by forty percent")])
    second = extracted(experiences=[experience(GOOD)])
    llm = _llm(first, second)

    result = await extract_resume(llm, RESUME_TEXT, NOW)

    assert result.resume.experiences[0].bullets == [GOOD]
    assert result.warnings == []
    assert len(llm.calls) == 2
    assert "Cut p95 latency by forty percent" in llm.calls[1].prompt
    assert "Cut p95 latency" not in llm.calls[0].prompt


async def test_a_persistent_paraphrase_is_dropped_with_a_warning_and_the_rest_is_kept() -> None:
    bad = "Cut p95 latency by forty percent"
    llm = _llm(
        extracted(experiences=[experience(GOOD, bad)]),
        extracted(experiences=[experience(GOOD, bad)]),
    )

    result = await extract_resume(llm, RESUME_TEXT, NOW)

    assert result.resume.experiences[0].bullets == [GOOD]
    assert [(w.code, w.count) for w in result.warnings] == [("dropped_unverified_items", 1)]
    assert len(llm.calls) == 2


async def test_a_translated_bullet_is_not_kept() -> None:
    text = "Experiência\n• Reduzi a latência da API em 40%\n"
    answer = extracted(experiences=[experience("Reduced API latency by 40%")])

    result = await extract_resume(_llm(answer, answer), text, NOW)

    assert result.resume.experiences[0].bullets == []


async def test_experiences_with_unusable_dates_are_reported_as_a_warning() -> None:
    answer = extracted(
        experiences=[
            experience(GOOD, start=None),
            experience(WRAPPED, start="2020-01", end="2020-12"),
        ]
    )

    result = await extract_resume(_llm(answer), RESUME_TEXT, NOW)

    assert result.total_experience_months == 12
    assert [(w.code, w.count) for w in result.warnings] == [("experiences_without_valid_dates", 1)]


async def test_a_total_given_by_the_model_is_ignored() -> None:
    answer = (
        '{"summary": null, "skills": [], "experiences": [{"title": "Dev", "company": null, '
        '"start": "2020-01", "end": "2020-12", "is_current": false, "bullets": []}], '
        '"education": [], "languages": [], "certifications": [], "projects": [], '
        '"total_years": 99, "total_experience_months": 999}'
    )

    result = await extract_resume(_llm(answer), RESUME_TEXT, NOW)

    assert result.total_experience_months == 12
    assert result.total_experience_years == 1.0


async def test_contact_details_in_the_resume_do_not_reach_the_result() -> None:
    text = RESUME_TEXT + "\nContato: jane@example.com +55 11 99999-0000 linkedin.com/in/jane\n"

    result = await extract_resume(_llm(extracted()), text, NOW)

    dumped = result.model_dump_json()
    assert "jane@example.com" not in dumped
    assert "99999-0000" not in dumped
    assert "linkedin" not in dumped


async def test_unusable_output_propagates_and_nothing_is_returned() -> None:
    llm = _llm(LLMInvalidOutputError("bad"))

    with pytest.raises(LLMInvalidOutputError):
        await extract_resume(llm, RESUME_TEXT, NOW)


async def test_logs_have_counts_and_no_resume_text(caplog: pytest.LogCaptureFixture) -> None:
    answer = extracted(experiences=[experience(GOOD, "Invented bullet")])
    llm = _llm(answer, answer)

    with caplog.at_level(logging.DEBUG):
        await extract_resume(llm, RESUME_TEXT, NOW)

    (record,) = [r for r in caplog.records if r.name == "app.ai.extraction.resume"]
    assert record.__dict__["dropped_items"] == 1
    assert record.__dict__["correction_round"] is True
    logged = " ".join(str(r.__dict__) + r.getMessage() for r in caplog.records)
    for fragment in ("p95", "Spring Boot", "Invented bullet", "Backend Developer"):
        assert fragment not in logged
