import math
from datetime import UTC, datetime

import pytest

from app.ai.extraction.job import extract_job
from app.ai.extraction.verify import comparison_key, is_verbatim, normalize
from app.ai.llm import LLMClient, LLMTransientError
from tests.fixtures.job_postings import ENGLISH, PORTUGUESE, Posting

pytestmark = pytest.mark.real_provider


@pytest.mark.parametrize("posting", [ENGLISH, PORTUGUESE], ids=["english", "portuguese"])
async def test_the_configured_model_extracts_a_usable_job(
    real_llm: LLMClient, posting: Posting
) -> None:
    try:
        result = await extract_job(real_llm, posting.text, datetime.now(UTC))
    except LLMTransientError as error:
        pytest.skip(f"the configured provider is not reachable or is rate limiting: {error}")

    job = result.job
    normalized_posting = normalize(posting.text)
    assert job.language == posting.language
    assert job.requirements, "the model returned no requirement that exists in the posting"
    assert all(is_verbatim(r.source_text, normalized_posting) for r in job.requirements)

    by_source = {comparison_key(r.source_text): r for r in job.requirements}
    expected_must = [s for s in posting.requirements if s[3] == "must_have"]
    found_must = [
        s
        for s in expected_must
        if (r := by_source.get(comparison_key(s[0]))) and r.priority == "must_have"
    ]
    assert len(found_must) >= math.ceil(len(expected_must) / 2)
    for source_text, _, _, priority, *_ in posting.requirements:
        found = by_source.get(comparison_key(source_text))
        if priority == "nice_to_have" and found is not None:
            assert found.priority == "nice_to_have", source_text
