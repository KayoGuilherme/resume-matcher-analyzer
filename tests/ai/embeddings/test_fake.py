import math

from app.ai.embeddings.fake import FakeEmbeddingClient


async def test_the_same_text_always_gives_the_same_vector_in_any_batch() -> None:
    fake = FakeEmbeddingClient(dimension=16)

    alone = (await fake.embed(["hello"]))[0]
    in_batch = (await fake.embed(["other", "hello"]))[1]

    assert alone == in_batch


async def test_different_texts_give_different_vectors() -> None:
    first, second = await FakeEmbeddingClient(dimension=16).embed(["hello", "hello!"])

    assert first != second


async def test_vectors_have_the_requested_dimension_and_unit_length() -> None:
    (vector,) = await FakeEmbeddingClient(dimension=1024).embed(["x"])

    assert len(vector) == 1024
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-9)


async def test_it_exposes_the_interface_and_records_calls() -> None:
    fake = FakeEmbeddingClient(dimension=8, model_name="m")

    await fake.embed(["a", "b"])

    assert (fake.model_name, fake.dimension) == ("m", 8)
    assert fake.calls == [["a", "b"]]
