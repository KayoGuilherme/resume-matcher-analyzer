"""Adapter for the OpenAI embeddings API; also serves OpenAI-compatible servers (Ollama, ...)."""

from collections.abc import Sequence
from typing import Any, Literal

import openai
from openai import AsyncOpenAI

from app.ai.embeddings.base import (
    EmbeddingAuthError,
    EmbeddingError,
    EmbeddingTimeoutError,
    EmbeddingTransientError,
)
from app.core.retry import retry_after_seconds


class OpenAIEmbeddingTransport:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        *,
        provider: Literal["openai", "openai_compatible"] = "openai",
        dimensions: int | None = None,
    ) -> None:
        """`dimensions` is sent only when given: hosted `text-embedding-3*` models can be cut
        to the column size; other models and compatible servers may reject the parameter."""
        self._client = client
        self._model = model
        self._provider = provider
        self._dimensions = dimensions

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        options: dict[str, Any] = {}
        if self._dimensions is not None:
            options["dimensions"] = self._dimensions
        try:
            # "float" explicitly: the SDK would otherwise ask for base64, which not every
            # compatible server supports.
            response = await self._client.embeddings.create(
                model=self._model, input=list(texts), encoding_format="float", **options
            )
        except openai.APITimeoutError:
            raise EmbeddingTimeoutError("The provider did not answer in time") from None
        except openai.APIConnectionError:
            raise EmbeddingTransientError("Could not connect to the provider") from None
        except openai.APIStatusError as error:
            status = error.status_code
            if status in {401, 403}:
                raise EmbeddingAuthError(
                    f"The provider rejected the credentials (status {status})"
                ) from None
            if status == 429 or status >= 500:
                raise EmbeddingTransientError(
                    f"The provider is unavailable (status {status})",
                    retry_after=retry_after_seconds(error.response.headers),
                ) from None
            raise EmbeddingError(f"The provider rejected the request (status {status})") from None
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]
