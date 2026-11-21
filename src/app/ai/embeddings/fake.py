"""A deterministic `EmbeddingClient` for tests. No network, no model files."""

import hashlib
import math
from collections.abc import Sequence


class FakeEmbeddingClient:
    """Unit-length vectors derived from a hash of the text: the same text always gives the same
    vector (whatever the batch), different texts give different vectors."""

    def __init__(self, dimension: int = 1024, model_name: str = "fake-embedding") -> None:
        self._dimension = dimension
        self._model_name = model_name
        self.calls: list[list[str]] = []

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.shake_256(text.encode()).digest(self._dimension * 2)
        raw = [
            int.from_bytes(digest[i * 2 : i * 2 + 2], "big") / 32767.5 - 1.0
            for i in range(self._dimension)
        ]
        norm = math.sqrt(sum(value * value for value in raw)) or 1.0
        return [value / norm for value in raw]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]
