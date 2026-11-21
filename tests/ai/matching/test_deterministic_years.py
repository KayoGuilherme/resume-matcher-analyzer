from datetime import date

from app.ai.extraction.models import Experience
from app.ai.matching.deterministic import Hints, Settled, check
from app.ai.matching.models import RequirementInput
from app.ai.matching.text import ResumeIndex
from tests.ai.matching.builders import exp, kw, req, resume_input

TODAY = date(2026, 1, 15)


def _check(requirement: RequirementInput, *experiences: Experience) -> Settled | Hints:
    resume = resume_input("resume", experiences=experiences)
    return check(requirement.requirement, ResumeIndex(resume), TODAY)


def _java(min_years: float) -> RequirementInput:
    return req(f"{min_years}+ years of Java", min_years=min_years, keywords=[kw("Java")])


def test_enough_years_is_met_with_the_bullets_of_those_experiences() -> None:
    # 2019-01 .. 2022-05 is 41 distinct months
    outcome = _check(_java(3), exp("Built Java services", start="2019-01", end="2022-05"))

    assert isinstance(outcome, Settled) and outcome.verdict == "met"
    assert [e.quote for e in outcome.evidence] == ["Built Java services"]
    assert outcome.code == "years_reached" and outcome.params == {"years": 3.4, "required": 3}


def test_overlapping_experiences_are_counted_once() -> None:
    first = exp("Java at A", start="2019-01", end="2020-12")  # 24 months
    second = exp("Java at B", start="2020-07", end="2022-06")  # 24 months, 6 overlap: 42 total

    assert isinstance(_check(_java(3.5), first, second), Settled)
    outcome = _check(_java(3.6), first, second)
    assert isinstance(outcome, Hints) and outcome.resume_years == 3.5


def test_not_enough_years_settles_nothing_and_the_hint_holds_the_years() -> None:
    outcome = _check(_java(5), exp("Java services", start="2020-01", end="2022-06"))  # 30 months

    assert isinstance(outcome, Hints) and outcome.resume_years == 2.5


def test_exactly_the_minimum_is_met_and_one_month_less_is_not() -> None:
    assert isinstance(_check(_java(3), exp("Java", start="2020-01", end="2022-12")), Settled)
    assert isinstance(_check(_java(3), exp("Java", start="2020-01", end="2022-11")), Hints)


def test_without_keywords_every_experience_counts() -> None:
    requirement = req("5+ years of experience", category="years", min_years=5)
    outcome = _check(
        requirement,
        exp("First job", start="2016-01", end="2018-12"),
        exp("Second job", start="2019-01", end="2022-12"),
    )

    assert isinstance(outcome, Settled)
    assert [e.quote for e in outcome.evidence] == ["Second job", "First job"]  # most recent first


def test_an_experience_without_a_start_date_is_skipped_and_the_others_count() -> None:
    outcome = _check(
        _java(3),
        exp("Java without dates", start=None, end=None),
        exp("Java with dates", start="2020-01", end="2022-12"),
    )

    assert isinstance(outcome, Settled)
    assert [e.quote for e in outcome.evidence] == ["Java with dates"]


def test_a_current_experience_ends_this_month() -> None:
    current = exp("Java now", start="2025-01", end=None, is_current=True)  # 13 months

    assert isinstance(_check(_java(1), current), Settled)
    assert isinstance(_check(_java(1.1), current), Hints)


def test_ambiguous_short_keywords_select_nothing() -> None:
    requirement = req("3+ years of Go", min_years=3, keywords=[kw("Go")])

    outcome = _check(requirement, exp("Go services", start="2015-01", end="2022-12"))

    assert isinstance(outcome, Hints) and outcome.resume_years == 0


def test_keywords_in_the_title_count_the_months_but_need_a_bullet_to_be_quoted() -> None:
    title_only = exp(title="Java Developer", start="2018-01", end="2019-12")  # no bullets
    with_bullet = exp("Wrote Java code", start="2020-01", end="2021-12")

    outcome = _check(_java(4), title_only, with_bullet)

    assert isinstance(outcome, Settled)
    assert [e.quote for e in outcome.evidence] == ["Wrote Java code"]


def test_years_that_cannot_be_quoted_are_not_proof() -> None:
    outcome = _check(_java(2), exp(title="Java Developer", start="2018-01", end="2021-12"))

    assert isinstance(outcome, Hints) and outcome.resume_years == 4.0


def test_experiences_that_do_not_mention_the_keyword_do_not_count() -> None:
    outcome = _check(
        _java(3),
        exp("Wrote Python", start="2010-01", end="2020-12"),
        exp("Wrote Java", start="2021-01", end="2021-12"),
    )

    assert isinstance(outcome, Hints) and outcome.resume_years == 1.0


def test_at_most_three_bullets_are_the_evidence() -> None:
    experiences = [exp(f"Java {n}", start=f"{2010 + n}-01", end=f"{2010 + n}-12") for n in range(6)]

    outcome = _check(_java(3), *experiences)

    assert isinstance(outcome, Settled)
    assert [e.quote for e in outcome.evidence] == ["Java 5", "Java 4", "Java 3"]


def test_the_bullet_that_shows_the_keyword_is_preferred() -> None:
    outcome = _check(
        _java(1), exp("Mentored juniors", "Optimized Java queries", start="2020-01", end="2021-12")
    )

    assert isinstance(outcome, Settled)
    assert [e.quote for e in outcome.evidence] == ["Optimized Java queries"]
