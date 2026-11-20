"""The provider-independent embeddings interface, its typed errors and the shared wrapper.

Business code depends on `EmbeddingClient` only. Adapters implement the small
`EmbeddingTransport` protocol; `BatchingEmbeddingClient` adds batching, retries, the dimension
check and content-free logging on top. Messages never contain the texts or the vectors.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import Protocol

from app.core.retry import retry_async

logger = logging.getLogger(__name__)

BATCH_SIZE = 64
MAX_ATTEMPTS = 3


class EmbeddingError(Exception):
    """Base class for every failure of the embeddings layer. No provider exception escapes it."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EmbeddingTransientError(EmbeddingError):
    """Rate limit, server error or connection problem. Worth retrying."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class EmbeddingAuthError(EmbeddingError):
    """Missing, wrong or forbidden credentials."""


class EmbeddingTimeoutError(EmbeddingError):
    """No answer within the timeout."""


class EmbeddingDimensionError(EmbeddingError):
    """The provider returned vectors of another size than EMBEDDING_DIMENSION."""

    def __init__(self, configured: int, received: int) -> None:
        super().__init__(
            f"The embedding model returned vectors of {received} numbers but "
            f"EMBEDDING_DIMENSION is {configured}. Fix EMBEDDING_DIMENSION or the model."
        )
        self.configured = configured
        self.received = received


class EmbeddingTransport(Protocol):
    """What an adapter implements: embed one batch, raising only typed errors."""

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmbeddingClient(Protocol):
    """Embed texts. One vector of `dimension` numbers per text, in the order given."""

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _is_transient(error: Exception) -> bool:
    return isinstance(error, EmbeddingTransientError)


def _retry_after(error: Exception) -> float | None:
    return error.retry_after if isinstance(error, EmbeddingTransientError) else None


class BatchingEmbeddingClient:
    """`EmbeddingClient` over a transport: batches, retries, checks dimensions, logs."""

    def __init__(
        self,
        transport: EmbeddingTransport,
        *,
        dimension: int,
        batch_size: int = BATCH_SIZE,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,  # noqa: S311 - jitter, not security
    ) -> None:
        self._transport = transport
        self._dimension = dimension
        self._batch_size = batch_size
        self._sleep = sleep
        self._rng = rng

    @property
    def transport(self) -> EmbeddingTransport:
        return self._transport

    @property
    def provider(self) -> str:
        return self._transport.provider

    @property
    def model_name(self) -> str:
        return self._transport.model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        started = time.perf_counter()
        vectors: list[list[float]] = []
        outcome = "success"
        batches = 0
        try:
            for start in range(0, len(texts), self._batch_size):
                batch = texts[start : start + self._batch_size]
                batches += 1
                result = await retry_async(
                    partial(self._transport.embed_batch, batch),
                    is_retryable=_is_transient,
                    attempts=MAX_ATTEMPTS,
                    delay_hint=_retry_after,
                    sleep=self._sleep,
                    rng=self._rng,
                )
                if len(result) != len(batch):
                    raise EmbeddingError("The provider returned a different number of vectors")
                for vector in result:
                    if len(vector) != self._dimension:
                        raise EmbeddingDimensionError(self._dimension, len(vector))
                vectors.extend(result)
            return vectors
        except EmbeddingError as error:
            outcome = type(error).__name__
            raise
        finally:
            logger.log(
                logging.INFO if outcome == "success" else logging.WARNING,
                "embedding call",
                extra={
                    "embedding_provider": self.provider,
                    "embedding_model": self.model_name,
                    "text_count": len(texts),
                    "batches": batches,
                    "outcome": outcome,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                },
            )
