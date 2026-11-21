import pytest

from app.core.retry import retry_async


class Transient(Exception):
    pass


class Fatal(Exception):
    pass


class Script:
    """Raises the given errors in order, then returns "ok"."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def _retryable(error: Exception) -> bool:
    return isinstance(error, Transient)


async def test_success_without_retry_does_not_sleep() -> None:
    sleeps, script = Sleeps(), Script()

    result = await retry_async(script, is_retryable=_retryable, sleep=sleeps)

    assert (result, script.calls, sleeps.delays) == ("ok", 1, [])


async def test_succeeds_on_the_third_attempt() -> None:
    sleeps, script = Sleeps(), Script(Transient(), Transient())

    result = await retry_async(script, is_retryable=_retryable, sleep=sleeps, rng=lambda: 1.0)

    assert (result, script.calls) == ("ok", 3)
    assert sleeps.delays == [1.0, 2.0]


async def test_exhaustion_re_raises_the_last_error() -> None:
    sleeps = Sleeps()
    script = Script(Transient("a"), Transient("b"), Transient("c"), Transient("d"))

    with pytest.raises(Transient, match="c"):
        await retry_async(script, is_retryable=_retryable, sleep=sleeps, attempts=3)

    assert script.calls == 3
    assert len(sleeps.delays) == 2


async def test_non_retryable_errors_are_raised_immediately() -> None:
    sleeps, script = Sleeps(), Script(Fatal())

    with pytest.raises(Fatal):
        await retry_async(script, is_retryable=_retryable, sleep=sleeps)

    assert (script.calls, sleeps.delays) == (1, [])


async def test_delays_grow_and_are_capped() -> None:
    sleeps = Sleeps()
    script = Script(*[Transient() for _ in range(5)])

    await retry_async(
        script,
        is_retryable=_retryable,
        attempts=6,
        base_delay=1.0,
        factor=4.0,
        max_delay=10.0,
        sleep=sleeps,
        rng=lambda: 1.0,
    )

    assert sleeps.delays == [1.0, 4.0, 10.0, 10.0, 10.0]


async def test_jitter_scales_the_delay() -> None:
    sleeps, script = Sleeps(), Script(Transient())

    await retry_async(script, is_retryable=_retryable, sleep=sleeps, rng=lambda: 0.5)

    assert sleeps.delays == [0.5]


async def test_a_delay_hint_wins_and_is_capped() -> None:
    sleeps = Sleeps()
    script = Script(Transient(), Transient())

    await retry_async(
        script,
        is_retryable=_retryable,
        sleep=sleeps,
        max_delay=5.0,
        delay_hint=lambda error: 2.0 if script.calls == 1 else 60.0,
    )

    assert sleeps.delays == [2.0, 5.0]


async def test_zero_attempts_is_rejected() -> None:
    with pytest.raises(ValueError, match="attempts"):
        await retry_async(Script(), is_retryable=_retryable, attempts=0)
