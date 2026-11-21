from datetime import UTC, datetime

import pytest

from app.ai.extraction.job import extract_job
from app.ai.extraction.job_models import JobExtractionResult
from app.ai.llm.fake import FakeLLMClient
from tests.fixtures.job_postings import POSTINGS, Posting, Summary

NOW = datetime(2026, 11, 21, tzinfo=UTC)


def _summaries(result: JobExtractionResult) -> list[Summary]:
    return [
        (
            r.source_text,
            r.text,
            r.category,
            r.priority,
            r.min_years,
            r.priority_unclear,
            [(k.normalized, k.synonyms) for k in r.keywords],
        )
        for r in result.job.requirements
    ]


@pytest.mark.parametrize("posting", POSTINGS, ids=[p.name for p in POSTINGS])
async def test_extraction_with_a_scripted_model_gives_the_expected_lists(posting: Posting) -> None:
    llm = FakeLLMClient(list(posting.answers))

    result = await extract_job(llm, posting.text, NOW)

    assert _summaries(result) == posting.requirements
    assert result.job.responsibilities == posting.responsibilities
    assert result.job.ats_keywords == posting.ats_keywords
    assert (result.job.language, result.job.seniority) == (posting.language, posting.seniority)
    assert {w.code: w.count for w in result.warnings} == posting.warnings
    assert len(llm.calls) == posting.llm_calls
    assert len({r.id for r in result.job.requirements}) == len(posting.requirements)


def test_the_postings_are_in_english_and_portuguese_and_have_sections() -> None:
    languages = {p.language for p in POSTINGS}

    assert {"en", "pt"} <= languages
    assert any("Nice to have:" in p.text for p in POSTINGS)
    assert any("Diferenciais:" in p.text for p in POSTINGS)


def test_every_expected_source_text_is_really_in_its_posting() -> None:
    from app.ai.extraction.verify import is_verbatim, normalize

    for posting in POSTINGS:
        normalized = normalize(posting.text)
        for source_text, *_ in posting.requirements:
            assert is_verbatim(source_text, normalized), (posting.name, source_text)
