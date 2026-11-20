"""Business rules for the candidate profile."""

import logging
from collections import defaultdict
from collections.abc import Sequence

from app.core.errors import DomainError
from app.core.normalization import normalize_language_name, normalize_stack_name
from app.profile.repository import ProfileRepository
from app.profile.schemas import LanguageOut, ProfileIn, ProfileOut, StackOut

logger = logging.getLogger(__name__)


class InvalidProfileError(DomainError):
    status_code = 422
    code = "invalid_profile"


class ProfileNotFoundError(DomainError):
    status_code = 404
    code = "profile_not_found"


def _positions(field: str, indexes: Sequence[int]) -> str:
    names = [f"{field}[{index}]" for index in indexes]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _duplicates(field: str, names: Sequence[str]) -> list[str]:
    """Report items sharing a normalized name, by position only (never by profile text)."""
    by_name: defaultdict[str, list[int]] = defaultdict(list)
    for index, name in enumerate(names):
        by_name[name].append(index)
    return [
        f"{_positions(field, indexes)}: same name after normalization"
        for indexes in by_name.values()
        if len(indexes) > 1
    ]


class ProfileService:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def save(self, data: ProfileIn) -> ProfileOut:
        """Normalize and validate the profile, then create or replace the stored one."""
        stacks = [
            StackOut(
                name=normalize_stack_name(item.name),
                original_name=item.name,
                years=item.years,
                level=item.level,
                last_year_used=item.last_year_used,
            )
            for item in data.stacks
        ]
        languages = [
            LanguageOut(
                name=normalize_language_name(item.name),
                original_name=item.name,
                level=item.level,
            )
            for item in data.languages
        ]

        violations = [
            f"stacks[{index}]: years exceed total_years_coding"
            for index, stack in enumerate(stacks)
            if stack.years > data.total_years_coding
        ]
        violations += _duplicates("stacks", [stack.name for stack in stacks])
        violations += _duplicates("languages", [language.name for language in languages])
        if violations:
            raise InvalidProfileError("; ".join(violations))

        profile = ProfileOut(
            target_role=data.target_role,
            seniority=data.seniority,
            total_years_coding=data.total_years_coding,
            stacks=stacks,
            languages=languages,
            notable_facts=data.notable_facts,
        )
        await self._repository.save(profile)
        # Counts only: the profile is personal data and must not reach the logs.
        logger.info(
            "profile saved",
            extra={"stack_count": len(stacks), "language_count": len(languages)},
        )
        return profile

    async def get(self) -> ProfileOut:
        profile = await self._repository.get()
        if profile is None:
            raise ProfileNotFoundError("No profile has been saved yet")
        return profile
