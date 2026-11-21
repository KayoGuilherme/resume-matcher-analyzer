"""Total experience, computed from dates by code and never by the LLM."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.ai.extraction.models import ExtractedExperience


@dataclass(frozen=True)
class ExperienceTotal:
    months: int
    skipped: int  # experiences left out because their dates are incomplete or inconsistent

    @property
    def years(self) -> float:
        return round(self.months / 12, 1)


def _month_number(year_month: str) -> int:
    return int(year_month[:4]) * 12 + int(year_month[5:7]) - 1


def total_experience_months(
    experiences: Sequence[ExtractedExperience], today: date
) -> ExperienceTotal:
    """Distinct calendar months covered by the experiences, start and end months included.

    A current experience ends in the month of `today`. Overlapping or adjacent experiences are
    merged, so nothing is counted twice. An experience without a start, without an end that is
    not current, or ending before it starts does not count.
    """
    this_month = today.year * 12 + today.month - 1
    intervals: list[tuple[int, int]] = []
    skipped = 0
    for experience in experiences:
        if experience.start is None:
            skipped += 1
            continue
        start = _month_number(experience.start)
        if experience.is_current:
            end = this_month
        elif experience.end is not None:
            end = _month_number(experience.end)
        else:
            skipped += 1
            continue
        if end < start:
            skipped += 1
            continue
        intervals.append((start, end))

    months = 0
    current: tuple[int, int] | None = None
    for start, end in sorted(intervals):
        if current is not None and start <= current[1] + 1:
            current = (current[0], max(current[1], end))
            continue
        if current is not None:
            months += current[1] - current[0] + 1
        current = (start, end)
    if current is not None:
        months += current[1] - current[0] + 1
    return ExperienceTotal(months=months, skipped=skipped)
