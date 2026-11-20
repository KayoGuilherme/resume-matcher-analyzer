"""Local embeddings with sentence-transformers (optional dependency group `local-embeddings`)."""

import threading
from collections.abc import Callable, Sequence
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.ai.embeddings.base import EmbeddingError

MISSING_PACKAGE_MESSAGE = (
    "EMBEDDING_PROVIDER=local needs the optional dependency group: run "
    "`uv sync --extra local-embeddings` (or build the image with the documented EXTRAS argument)."
)


def load_sentence_transformer(model_name: str) -> Any:
    """Import lazily: the package is large and optional, so the module must import without it."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise EmbeddingError(MISSING_PACKAGE_MESSAGE) from None
    return SentenceTransformer(model_name)


class LocalEmbeddingTransport:
    """Runs the model in a worker thread so the event loop is never blocked."""

    def __init__(
        self,
        model_name: str,
        *,
        loader: Callable[[str], Any] = load_sentence_transformer,
    ) -> None:
        self._model_name = model_name
        self._loader = loader
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def provider(self) -> str:
        return "local"

    @property
    def model(self) -> str:
        return self._model_name

    def _encode(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            if self._model is None:
                self._model = self._loader(self._model_name)
        encoded = self._model.encode(texts, normalize_embeddings=True)
        return [[float(value) for value in vector] for vector in encoded]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            return await run_in_threadpool(self._encode, list(texts))
        except EmbeddingError:
            raise
        except Exception as error:
            # The exception text may contain model paths or content; keep the type only.
            raise EmbeddingError(
                f"The local embedding model failed ({type(error).__name__})"
            ) from None
