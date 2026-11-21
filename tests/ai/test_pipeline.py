from datetime import UTC, datetime

import pytest

from app.ai.embeddings.base import EmbeddingTransientError
from app.ai.embeddings.fake import FakeEmbeddingClient
from app.ai.llm.fake import FakeLLMClient
from app.ai.pipeline import process_job_text, process_resume_text
from tests.ai.extraction.builders import RESUME_TEXT, experience, extracted
from tests.ai.extraction.job_builders import job
from tests.fixtures.job_postings import ENGLISH, POSTINGS, Posting

NOW = datetime(2024, 6, 15, tzinfo=UTC)


async def test_chunks_get_vectors_of_the_right_size_and_the_model_name() -> None:
    llm = FakeLLMClient(
        [
            extracted(
                experiences=[experience("Reduced p95 latency by 40%")],
                skills=["Cloud: AWS, Docker"],
            )
        ]
    )
    embedder = FakeEmbeddingClient(dimension=16, model_name="fake-bge")

    processed = await process_resume_text(RESUME_TEXT, llm, embedder, NOW)

    assert processed.embedding_model == "fake-bge"
    assert [c.chunk.text for c in processed.chunks] == [
        "Cloud: AWS, Docker",
        "Reduced p95 latency by 40%",
    ]
    assert all(len(c.embedding) == 16 for c in processed.chunks)
    assert embedder.calls == [["Cloud: AWS, Docker", "Reduced p95 latency by 40%"]]
    assert processed.extraction.resume.experiences[0].bullets == ["Reduced p95 latency by 40%"]
    assert processed.extraction.total_experience_months == 24


async def test_no_chunks_means_no_embedding_call() -> None:
    embedder = FakeEmbeddingClient(dimension=16)

    processed = await process_resume_text(RESUME_TEXT, FakeLLMClient([extracted()]), embedder, NOW)

    assert processed.chunks == []
    assert embedder.calls == []


async def test_an_embedding_error_propagates_unchanged() -> None:
    class Failing(FakeEmbeddingClient):
        async def embed(self, texts):  # type: ignore[no-untyped-def]
            raise EmbeddingTransientError("status 503")

    llm = FakeLLMClient([extracted(skills=["Cloud: AWS, Docker"])])

    with pytest.raises(EmbeddingTransientError):
        await process_resume_text(RESUME_TEXT, llm, Failing(16), NOW)


# --- jobs ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("posting", POSTINGS, ids=[p.name for p in POSTINGS])
async def test_each_surviving_requirement_gets_a_vector_of_its_text(posting: Posting) -> None:
    embedder = FakeEmbeddingClient(dimension=16, model_name="fake-bge")

    processed = await process_job_text(
        posting.text, FakeLLMClient(list(posting.answers)), embedder, NOW
    )

    texts = [r.text for r in processed.extraction.job.requirements]
    assert texts == [summary[1] for summary in posting.requirements]
    assert embedder.calls == [texts]
    assert [e.position for e in processed.requirements] == list(range(len(texts)))
    assert [e.requirement.text for e in processed.requirements] == texts
    assert all(len(e.embedding) == 16 for e in processed.requirements)
    assert processed.embedding_model == "fake-bge"
    assert processed.requirements[0].requirement.id == processed.extraction.job.requirements[0].id


async def test_a_job_without_requirements_makes_no_embedding_call() -> None:
    embedder = FakeEmbeddingClient(dimension=16)

    processed = await process_job_text("Some posting", FakeLLMClient([job()]), embedder, NOW)

    assert processed.requirements == []
    assert embedder.calls == []


async def test_a_job_embedding_error_propagates_unchanged() -> None:
    class Failing(FakeEmbeddingClient):
        async def embed(self, texts):  # type: ignore[no-untyped-def]
            raise EmbeddingTransientError("status 503")

    with pytest.raises(EmbeddingTransientError):
        await process_job_text(ENGLISH.text, FakeLLMClient(list(ENGLISH.answers)), Failing(16), NOW)
