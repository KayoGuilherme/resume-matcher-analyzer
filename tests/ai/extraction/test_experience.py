from datetime import date

import pytest

from app.ai.extraction.experience import total_experience_months
from tests.ai.extraction.builders import experience

TODAY = date(2024, 6, 15)


def _total(*experiences: object) -> tuple[int, float, int]:
    result = total_experience_months(list(experiences), TODAY)  # type: ignore[arg-type]
    return result.months, result.years, result.skipped


def test_sequential_jobs_add_up() -> None:
    assert _total(
        experience(start="2018-01", end="2019-12"), experience(start="2020-03", end="2021-02")
    ) == (36, 3.0, 0)


def test_overlapping_jobs_are_not_counted_twice() -> None:
    assert (
        _total(
            experience(start="2020-01", end="2021-12"), experience(start="2021-06", end="2022-05")
        )[0]
        == 29
    )


def test_a_job_inside_another_adds_nothing() -> None:
    assert (
        _total(
            experience(start="2020-01", end="2020-12"), experience(start="2020-03", end="2020-06")
        )[0]
        == 12
    )


def test_the_order_of_the_jobs_does_not_matter() -> None:
    first = experience(start="2018-01", end="2018-12")
    second = experience(start="2017-06", end="2018-03")

    assert _total(first, second) == _total(second, first)
    assert _total(first, second)[0] == 19


def test_adjacent_months_are_merged_without_double_counting() -> None:
    assert (
        _total(
            experience(start="2020-01", end="2020-06"), experience(start="2020-07", end="2020-12")
        )[0]
        == 12
    )


def test_the_start_and_end_months_are_both_included() -> None:
    assert _total(experience(start="2020-05", end="2020-05"))[0] == 1


def test_a_current_job_ends_in_the_current_month() -> None:
    assert _total(experience(start="2024-01", end=None, is_current=True))[0] == 6


def test_current_wins_over_a_given_end() -> None:
    assert _total(experience(start="2024-01", end="2024-02", is_current=True))[0] == 6


def test_a_job_without_a_start_is_skipped_and_counted() -> None:
    assert _total(
        experience(start=None, end="2020-01"), experience(start="2020-01", end="2020-12")
    ) == (
        12,
        1.0,
        1,
    )


def test_a_finished_job_without_an_end_is_skipped() -> None:
    assert _total(experience(start="2020-01", end=None)) == (0, 0.0, 1)


def test_an_end_before_the_start_is_skipped() -> None:
    assert _total(experience(start="2021-01", end="2020-01")) == (0, 0.0, 1)


def test_a_current_job_starting_in_the_future_is_skipped() -> None:
    assert _total(experience(start="2025-01", end=None, is_current=True)) == (0, 0.0, 1)


def test_no_experience_is_zero() -> None:
    assert _total() == (0, 0.0, 0)


@pytest.mark.parametrize(("months", "years"), [(18, 1.5), (20, 1.7), (7, 0.6)])
def test_years_are_months_over_twelve_rounded_to_one_decimal(months: int, years: float) -> None:
    end = f"{2020 + (months - 1) // 12}-{(months - 1) % 12 + 1:02d}"

    assert _total(experience(start="2020-01", end=end))[:2] == (months, years)
