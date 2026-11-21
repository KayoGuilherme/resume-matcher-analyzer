import math

import pytest

from app.ai.embeddings import EmbeddingClient, EmbeddingTransientError

pytestmark = pytest.mark.real_provider


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


async def test_portuguese_and_english_sentences_embed_close_to_their_translation(
    real_embedder: EmbeddingClient,
) -> None:
    texts = [
        "Desenvolvi APIs REST para uma plataforma de pagamentos.",
        "I built REST APIs for a payments platform.",
        "The quarterly tax declaration is due next Friday.",
    ]
    try:
        portuguese, english, unrelated = await real_embedder.embed(texts)
    except EmbeddingTransientError as error:
        pytest.skip(f"the configured embeddings provider is not reachable: {error}")

    assert len(portuguese) == real_embedder.dimension
    assert _cosine(portuguese, english) > _cosine(portuguese, unrelated)
