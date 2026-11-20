from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.profile.schemas import ProfileIn

THIS_YEAR = datetime.now(UTC).year


def _profile(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "target_role": "Backend Developer",
        "seniority": "mid",
        "total_years_coding": 5,
        "stacks": [{"name": "Python", "years": 4, "level": "proficient", "last_year_used": 2024}],
        "languages": [{"name": "pt", "level": "native"}],
        "notable_facts": ["Built a payments API"],
    }
    data.update(overrides)
    return data


def _fields_with_errors(data: dict[str, Any]) -> set[str]:
    with pytest.raises(ValidationError) as info:
        ProfileIn.model_validate(data)
    return {".".join(str(part) for part in error["loc"]) for error in info.value.errors()}


def test_valid_profile_is_accepted() -> None:
    profile = ProfileIn.model_validate(_profile())

    assert profile.target_role == "Backend Developer"
    assert profile.stacks[0].last_year_used == 2024


def test_empty_lists_are_accepted() -> None:
    profile = ProfileIn.model_validate(_profile(stacks=[], languages=[], notable_facts=[]))

    assert profile.stacks == [] and profile.languages == [] and profile.notable_facts == []


@pytest.mark.parametrize("seniority", ["junior", "mid", "senior"])
def test_known_seniorities_are_accepted(seniority: str) -> None:
    assert ProfileIn.model_validate(_profile(seniority=seniority)).seniority == seniority


def test_unknown_seniority_is_rejected() -> None:
    assert _fields_with_errors(_profile(seniority="principal")) == {"seniority"}


@pytest.mark.parametrize("level", ["learning", "working", "proficient", "expert"])
def test_known_stack_levels_are_accepted(level: str) -> None:
    stack = {"name": "Go", "years": 1, "level": level}

    assert ProfileIn.model_validate(_profile(stacks=[stack])).stacks[0].level == level


def test_unknown_stack_level_is_rejected() -> None:
    stack = {"name": "Go", "years": 1, "level": "guru"}

    assert _fields_with_errors(_profile(stacks=[stack])) == {"stacks.0.level"}


@pytest.mark.parametrize("level", ["A1", "A2", "B1", "B2", "C1", "C2", "native"])
def test_known_language_levels_are_accepted(level: str) -> None:
    languages = [{"name": "english", "level": level}]

    assert ProfileIn.model_validate(_profile(languages=languages)).languages[0].level == level


def test_unknown_language_level_is_rejected() -> None:
    languages = [{"name": "english", "level": "D1"}]

    assert _fields_with_errors(_profile(languages=languages)) == {"languages.0.level"}


def test_negative_years_are_rejected() -> None:
    stack = {"name": "Go", "years": -1, "level": "working"}

    assert _fields_with_errors(_profile(total_years_coding=-1, stacks=[stack])) == {
        "total_years_coding",
        "stacks.0.years",
    }


@pytest.mark.parametrize("years", [61, float("inf"), float("nan")])
def test_years_must_be_finite_and_at_most_sixty(years: float) -> None:
    assert _fields_with_errors(_profile(total_years_coding=years)) == {"total_years_coding"}


def test_fractional_years_and_sixty_are_accepted() -> None:
    profile = ProfileIn.model_validate(_profile(total_years_coding=60, stacks=[]))
    half = {"name": "Go", "years": 0.5, "level": "learning"}

    assert profile.total_years_coding == 60
    assert ProfileIn.model_validate(_profile(stacks=[half])).stacks[0].years == 0.5


def test_text_is_stripped_and_must_not_be_empty() -> None:
    profile = ProfileIn.model_validate(_profile(target_role="  Dev  ", notable_facts=[" fact "]))

    assert profile.target_role == "Dev"
    assert profile.notable_facts == ["fact"]
    assert _fields_with_errors(_profile(target_role="   ")) == {"target_role"}
    assert _fields_with_errors(_profile(notable_facts=[""])) == {"notable_facts.0"}


def test_text_length_limits() -> None:
    assert _fields_with_errors(_profile(target_role="x" * 101)) == {"target_role"}
    assert _fields_with_errors(_profile(notable_facts=["x" * 1001])) == {"notable_facts.0"}
    assert ProfileIn.model_validate(_profile(notable_facts=["x" * 1000]))


def test_list_size_limits() -> None:
    stack = {"name": "Go", "years": 1, "level": "working"}
    language = {"name": "english", "level": "B2"}

    assert _fields_with_errors(_profile(stacks=[stack] * 101)) == {"stacks"}
    assert _fields_with_errors(_profile(languages=[language] * 21)) == {"languages"}
    assert _fields_with_errors(_profile(notable_facts=["x"] * 101)) == {"notable_facts"}
    assert ProfileIn.model_validate(_profile(stacks=[stack] * 100, languages=[language] * 20))


def test_missing_required_field_is_rejected() -> None:
    data = _profile()
    del data["target_role"]

    assert _fields_with_errors(data) == {"target_role"}


def test_unknown_field_is_rejected() -> None:
    assert _fields_with_errors(_profile(senority="mid")) == {"senority"}


def test_last_year_used_is_optional() -> None:
    stack = {"name": "Go", "years": 1, "level": "working"}

    assert ProfileIn.model_validate(_profile(stacks=[stack])).stacks[0].last_year_used is None


@pytest.mark.parametrize("year", [1970, THIS_YEAR])
def test_last_year_used_bounds_are_accepted(year: int) -> None:
    stack = {"name": "Go", "years": 1, "level": "working", "last_year_used": year}

    assert ProfileIn.model_validate(_profile(stacks=[stack])).stacks[0].last_year_used == year


@pytest.mark.parametrize("year", [1969, THIS_YEAR + 1])
def test_last_year_used_outside_bounds_is_rejected(year: int) -> None:
    stack = {"name": "Go", "years": 1, "level": "working", "last_year_used": year}

    assert _fields_with_errors(_profile(stacks=[stack])) == {"stacks.0.last_year_used"}
