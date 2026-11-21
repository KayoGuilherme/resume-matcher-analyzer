import logging

import pytest

from app.ai.embeddings.base import (
    BatchingEmbeddingClient,
    EmbeddingAuthError,
    EmbeddingClient,
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingTimeoutError,
    EmbeddingTransientError,
)
from tests.ai.embeddings.transport import ScriptedEmbeddingTransport


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def _client(
    transport: ScriptedEmbeddingTransport, *, batch_size: int = 64, sleeps: Sleeps | None = None
) -> BatchingEmbeddingClient:
    return BatchingEmbeddingClient(
        transport,
        dimension=transport.dimension,
        batch_size=batch_size,
        sleep=sleeps or Sleeps(),
        rng=lambda: 1.0,
    )


async def test_vectors_come_back_in_the_order_of_the_texts() -> None:
    client = _client(ScriptedEmbeddingTransport())

    vectors = await client.embed(["a", "bbb", "cc"])

    assert [vector[0] for vector in vectors] == [1.0, 3.0, 2.0]


async def test_exposes_the_model_name_and_dimension() -> None:
    client: EmbeddingClient = _client(ScriptedEmbeddingTransport(dimension=5))

    assert client.model_name == "scripted-embedding"
    assert client.dimension == 5


async def test_a_long_list_is_split_into_batches_and_kept_in_order() -> None:
    transport = ScriptedEmbeddingTransport()
    client = _client(transport)
    texts = ["x" * (i + 1) for i in range(150)]

    vectors = await client.embed(texts)

    assert [len(batch) for batch in transport.batches] == [64, 64, 22]
    assert [vector[0] for vector in vectors] == [float(i + 1) for i in range(150)]


async def test_an_empty_list_makes_no_request() -> None:
    transport = ScriptedEmbeddingTransport()

    assert await _client(transport).embed([]) == []
    assert transport.batches == []


async def test_a_transient_error_is_retried_with_a_backoff_wait() -> None:
    sleeps = Sleeps()
    transport = ScriptedEmbeddingTransport(script=[EmbeddingTransientError("status 500")])

    vectors = await _client(transport, sleeps=sleeps).embed(["a"])

    assert len(vectors) == 1
    assert len(transport.batches) == 2
    assert sleeps.delays == [1.0]


async def test_transient_errors_are_raised_after_three_attempts() -> None:
    transport = ScriptedEmbeddingTransport(script=[EmbeddingTransientError("x")] * 5)

    with pytest.raises(EmbeddingTransientError):
        await _client(transport).embed(["a"])

    assert len(transport.batches) == 3


@pytest.mark.parametrize("error", [EmbeddingAuthError("status 401"), EmbeddingTimeoutError("slow")])
async def test_auth_failures_and_timeouts_are_not_retried(error: EmbeddingError) -> None:
    transport = ScriptedEmbeddingTransport(script=[error])

    with pytest.raises(type(error)):
        await _client(transport).embed(["a"])

    assert len(transport.batches) == 1


async def test_a_vector_of_the_wrong_size_names_both_dimensions() -> None:
    transport = ScriptedEmbeddingTransport(dimension=1024, script=[[[0.0] * 768]])

    with pytest.raises(EmbeddingDimensionError) as exc_info:
        await _client(transport).embed(["a"])

    assert "1024" in exc_info.value.message
    assert "768" in exc_info.value.message
    assert (exc_info.value.configured, exc_info.value.received) == (1024, 768)


async def test_a_different_number_of_vectors_is_an_error() -> None:
    transport = ScriptedEmbeddingTransport(script=[[[0.0] * 3]])

    with pytest.raises(EmbeddingError):
        await _client(transport).embed(["a", "b"])


async def test_logs_have_counts_and_no_texts_or_vectors(caplog: pytest.LogCaptureFixture) -> None:
    client = _client(ScriptedEmbeddingTransport())

    with caplog.at_level(logging.DEBUG):
        await client.embed(["SECRET-BULLET-TEXT", "other"])

    (record,) = [r for r in caplog.records if r.name == "app.ai.embeddings.base"]
    assert record.__dict__["text_count"] == 2
    assert record.__dict__["embedding_model"] == "scripted-embedding"
    logged = " ".join(str(r.__dict__) + r.getMessage() for r in caplog.records)
    assert "SECRET-BULLET-TEXT" not in logged
    assert "18.0" not in logged  # the vector of the secret text
