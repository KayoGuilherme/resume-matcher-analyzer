import sys
import threading
from typing import Any

import pytest

from app.ai.embeddings.base import EmbeddingError
from app.ai.embeddings.local import MISSING_PACKAGE_MESSAGE, LocalEmbeddingTransport


class FakeModel:
    def __init__(self) -> None:
        self.threads: list[str] = []
        self.arguments: list[dict[str, Any]] = []

    def encode(self, texts: list[str], **kwargs: Any) -> list[tuple[float, ...]]:
        self.threads.append(threading.current_thread().name)
        self.arguments.append(kwargs)
        return [(float(len(text)), 0.5) for text in texts]


async def test_the_model_is_loaded_once_and_results_are_plain_float_lists() -> None:
    model = FakeModel()
    loads: list[str] = []

    def loader(name: str) -> FakeModel:
        loads.append(name)
        return model

    transport = LocalEmbeddingTransport("the-model", loader=loader)

    first = await transport.embed_batch(["ab", "c"])
    await transport.embed_batch(["d"])

    assert first == [[2.0, 0.5], [1.0, 0.5]]
    assert all(isinstance(v, float) for vector in first for v in vector)
    assert loads == ["the-model"]
    assert transport.provider == "local"
    assert transport.model == "the-model"
    assert model.arguments[0] == {"normalize_embeddings": True}


async def test_inference_runs_off_the_event_loop_thread() -> None:
    model = FakeModel()
    transport = LocalEmbeddingTransport("m", loader=lambda _name: model)

    await transport.embed_batch(["a"])

    assert model.threads[0] != threading.main_thread().name


async def test_model_failures_keep_the_exception_type_only() -> None:
    def loader(_name: str) -> Any:
        raise RuntimeError("path /secret/model and text SECRET-TEXT")

    transport = LocalEmbeddingTransport("m", loader=loader)

    with pytest.raises(EmbeddingError) as exc_info:
        await transport.embed_batch(["SECRET-TEXT"])

    assert "SECRET-TEXT" not in str(exc_info.value)
    assert "RuntimeError" in str(exc_info.value)


async def test_a_missing_optional_package_names_the_group_to_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # makes the import fail

    with pytest.raises(EmbeddingError) as exc_info:
        await LocalEmbeddingTransport("m").embed_batch(["a"])

    assert str(exc_info.value) == MISSING_PACKAGE_MESSAGE
    assert "local-embeddings" in MISSING_PACKAGE_MESSAGE


async def test_the_default_loader_builds_a_sentence_transformer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[str] = []

    class Module:
        class SentenceTransformer(FakeModel):
            def __init__(self, name: str) -> None:
                super().__init__()
                created.append(name)

    monkeypatch.setitem(sys.modules, "sentence_transformers", Module)

    vectors = await LocalEmbeddingTransport("bge-m3").embed_batch(["abc"])

    assert created == ["bge-m3"]
    assert vectors == [[3.0, 0.5]]
