from datetime import UTC, datetime

import pytest

from app.ai.embeddings.base import EmbeddingTransientError
from app.ai.embeddings.fake import FakeEmbeddingClient
from app.ai.llm.fake import FakeLLMClient
from app.ai.pipeline import process_resume_text
from tests.ai.extraction.builders import RESUME_TEXT, experience, extracted

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
