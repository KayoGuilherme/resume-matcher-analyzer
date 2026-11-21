"""Retry with exponential backoff and full jitter. Shared by the LLM and embeddings layers."""

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping


async def retry_async[T](
    fn: Callable[[], Awaitable[T]],
    *,
    is_retryable: Callable[[Exception], bool],
    attempts: int = 3,
    base_delay: float = 1.0,
    factor: float = 2.0,
    max_delay: float = 20.0,
    delay_hint: Callable[[Exception], float | None] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: Callable[[], float] = random.random,  # noqa: S311 - jitter, not security
) -> T:
    """Call `fn` up to `attempts` times, waiting between attempts while errors are retryable.

    The wait is a random fraction (full jitter) of `base_delay * factor ** n`, capped at
    `max_delay`. When `delay_hint` returns a number for the error (a Retry-After header) that
    delay is used instead, also capped. The last error is re-raised once the attempts run out.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    attempt = 1
    while True:
        try:
            return await fn()
        except Exception as error:
            if attempt >= attempts or not is_retryable(error):
                raise
            hint = delay_hint(error) if delay_hint is not None else None
            if hint is not None:
                delay = min(max(hint, 0.0), max_delay)
            else:
                delay = rng() * min(max_delay, base_delay * factor ** (attempt - 1))
            await sleep(delay)
            attempt += 1


def retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    """The `Retry-After` header as seconds, if it is a plain number."""
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None
