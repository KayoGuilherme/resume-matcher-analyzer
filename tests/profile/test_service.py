import logging
from typing import Any

import pytest

from app.profile.schemas import ProfileIn, ProfileOut
from app.profile.service import InvalidProfileError, ProfileNotFoundError, ProfileService


class FakeRepository:
    def __init__(self, stored: ProfileOut | None = None) -> None:
        self.stored = stored
        self.saved: list[ProfileOut] = []

    async def get(self) -> ProfileOut | None:
        return self.stored

    async def save(self, profile: ProfileOut) -> None:
        self.saved.append(profile)
        self.stored = profile


def _input(**overrides: Any) -> ProfileIn:
    data: dict[str, Any] = {
        "target_role": "Backend Developer",
        "seniority": "mid",
        "total_years_coding": 5,
        "stacks": [{"name": "Springboot", "years": 3, "level": "working"}],
        "languages": [{"name": "Português", "level": "native"}],
        "notable_facts": ["Built a payments API"],
    }
    data.update(overrides)
    return ProfileIn.model_validate(data)


def _service(repository: FakeRepository | None = None) -> tuple[ProfileService, FakeRepository]:
    repository = repository or FakeRepository()
    return ProfileService(repository), repository  # type: ignore[arg-type]


async def test_save_normalizes_names_and_keeps_the_original_text() -> None:
    service, repository = _service()

    profile = await service.save(_input())

    assert profile.stacks[0].name == "spring boot"
    assert profile.stacks[0].original_name == "Springboot"
    assert profile.languages[0].name == "portuguese"
    assert profile.languages[0].original_name == "Português"
    assert profile.stacks[0].last_year_used is None
    assert repository.saved == [profile]


async def test_save_returns_what_get_returns() -> None:
    service, _ = _service()

    saved = await service.save(_input())

    assert await service.get() == saved


async def test_duplicate_stacks_through_an_alias_are_rejected_by_position() -> None:
    service, repository = _service()
    stacks = [
        {"name": "Postgres", "years": 1, "level": "working"},
        {"name": "Go", "years": 1, "level": "working"},
        {"name": "PostgreSQL", "years": 2, "level": "expert"},
    ]

    with pytest.raises(InvalidProfileError) as info:
        await service.save(_input(stacks=stacks))

    assert info.value.message == "stacks[0] and stacks[2]: same name after normalization"
    assert "Postgres" not in info.value.message
    assert repository.saved == []


async def test_three_way_duplicate_lists_every_position() -> None:
    service, _ = _service()
    stacks = [{"name": name, "years": 1, "level": "working"} for name in ("js", "JS", "javascript")]

    with pytest.raises(InvalidProfileError) as info:
        await service.save(_input(stacks=stacks))

    assert info.value.message == "stacks[0], stacks[1] and stacks[2]: same name after normalization"


async def test_duplicate_languages_are_rejected() -> None:
    service, _ = _service()
    languages = [{"name": "pt", "level": "native"}, {"name": "Portuguese", "level": "B2"}]

    with pytest.raises(InvalidProfileError) as info:
        await service.save(_input(languages=languages))

    assert info.value.message == "languages[0] and languages[1]: same name after normalization"


async def test_same_name_in_stacks_and_languages_is_accepted() -> None:
    service, _ = _service()
    stacks = [{"name": "english", "years": 1, "level": "working"}]
    languages = [{"name": "English", "level": "C1"}]

    profile = await service.save(_input(stacks=stacks, languages=languages))

    assert profile.stacks[0].name == profile.languages[0].name == "english"


async def test_stack_years_may_equal_but_not_exceed_total_years() -> None:
    service, _ = _service()
    equal = [{"name": "Go", "years": 5, "level": "working"}]
    above = [{"name": "Go", "years": 5.5, "level": "working"}]

    await service.save(_input(stacks=equal))
    with pytest.raises(InvalidProfileError) as info:
        await service.save(_input(stacks=above))

    assert info.value.message == "stacks[0]: years exceed total_years_coding"


async def test_all_comparison_violations_are_reported_together() -> None:
    service, repository = _service()
    stacks = [
        {"name": "Go", "years": 9, "level": "working"},
        {"name": "Rust", "years": 9, "level": "working"},
    ]
    languages = [{"name": "en", "level": "B2"}, {"name": "English", "level": "C1"}]

    with pytest.raises(InvalidProfileError) as info:
        await service.save(_input(stacks=stacks, languages=languages))

    assert info.value.message.split("; ") == [
        "stacks[0]: years exceed total_years_coding",
        "stacks[1]: years exceed total_years_coding",
        "languages[0] and languages[1]: same name after normalization",
    ]
    assert repository.saved == []


async def test_rejected_save_leaves_the_stored_profile_untouched() -> None:
    service, repository = _service()
    stored = await service.save(_input())

    with pytest.raises(InvalidProfileError):
        await service.save(_input(total_years_coding=1))

    assert repository.stored == stored


async def test_get_without_a_profile_raises_not_found() -> None:
    service, _ = _service()

    with pytest.raises(ProfileNotFoundError) as info:
        await service.get()

    assert info.value.status_code == 404
    assert info.value.code == "profile_not_found"


def test_error_types_carry_the_documented_status_and_code() -> None:
    assert (InvalidProfileError.status_code, InvalidProfileError.code) == (422, "invalid_profile")


async def test_saving_does_not_log_profile_text(caplog: pytest.LogCaptureFixture) -> None:
    service, _ = _service()

    with caplog.at_level(logging.DEBUG):
        await service.save(_input(notable_facts=["PRIVATE-fact-text"]))
        with pytest.raises(InvalidProfileError):
            await service.save(_input(total_years_coding=0.5))

    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for text in ("PRIVATE-fact-text", "Backend Developer", "Springboot", "Português"):
        assert text not in logged
