from collections.abc import Sequence


class ScriptedEmbeddingTransport:
    """Embeds each text as `[float(len(text))] * dimension` unless a scripted item says
    otherwise (an exception to raise, or a fixed result for that call)."""

    def __init__(
        self,
        dimension: int = 3,
        script: Sequence[Exception | list[list[float]] | None] = (),
    ) -> None:
        self.dimension = dimension
        self._script = list(script)
        self.batches: list[list[str]] = []

    @property
    def provider(self) -> str:
        return "scripted"

    @property
    def model(self) -> str:
        return "scripted-embedding"

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        item = self._script.pop(0) if self._script else None
        if isinstance(item, Exception):
            raise item
        if item is not None:
            return item
        return [[float(len(text))] * self.dimension for text in texts]
