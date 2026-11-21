import asyncio
import math
import random
import uuid

from app.ai.matching.models import ChunkInput
from app.ai.matching.retrieval import rank_chunks, rank_chunks_async


def _chunks(count: int, dimension: int, rng: random.Random) -> list[ChunkInput]:
    return [
        ChunkInput(
            id=uuid.uuid4(),
            section="experience",
            experience_id=None,
            position=n,
            text=f"chunk {n}",
            embedding=[rng.uniform(-1, 1) for _ in range(dimension)],
        )
        for n in range(count)
    ]


async def test_the_async_ranking_equals_the_sync_one_for_a_realistic_analysis() -> None:
    rng = random.Random(7)  # noqa: S311 - seeded test data
    chunks = _chunks(300, 1024, rng)
    vectors = [[rng.uniform(-1, 1) for _ in range(1024)] for _ in range(30)]

    ranked = await rank_chunks_async(vectors, chunks, top_k=5, min_similarity=0.0)

    expected = [rank_chunks(v, chunks, top_k=5, min_similarity=0.0) for v in vectors]
    assert ranked == expected
    assert all(math.isfinite(item.similarity) for row in ranked for item in row)


async def test_the_ranking_does_not_block_the_event_loop() -> None:
    rng = random.Random(3)  # noqa: S311 - seeded test data
    chunks = _chunks(300, 1024, rng)
    vectors = [[rng.uniform(-1, 1) for _ in range(1024)] for _ in range(30)]
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0)
            ticks += 1

    task = asyncio.create_task(ticker())
    await rank_chunks_async(vectors, chunks, top_k=5, min_similarity=0.0)
    task.cancel()

    assert ticks > 1
