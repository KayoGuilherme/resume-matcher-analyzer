"""Request and response models for the candidate profile."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Seniority = Literal["junior", "mid", "senior"]
StackLevel = Literal["learning", "working", "proficient", "expert"]
LanguageLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2", "native"]

MAX_YEARS = 60
FIRST_YEAR = 1970

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Fact = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Years = Annotated[float, Field(ge=0, le=MAX_YEARS, allow_inf_nan=False)]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StackIn(_Request):
    name: Name
    years: Years
    level: StackLevel
    last_year_used: Annotated[int, Field(ge=FIRST_YEAR)] | None = None

    @field_validator("last_year_used")
    @classmethod
    def _not_in_the_future(cls, year: int | None) -> int | None:
        if year is not None and year > datetime.now(UTC).year:
            raise ValueError("must not be later than the current year")
        return year


class LanguageIn(_Request):
    name: Name
    level: LanguageLevel


class ProfileIn(_Request):
    target_role: Name
    seniority: Seniority
    total_years_coding: Years
    stacks: Annotated[list[StackIn], Field(max_length=100)]
    languages: Annotated[list[LanguageIn], Field(max_length=20)]
    notable_facts: Annotated[list[Fact], Field(max_length=100)]


class StackOut(BaseModel):
    name: str
    original_name: str
    years: float
    level: StackLevel
    last_year_used: int | None


class LanguageOut(BaseModel):
    name: str
    original_name: str
    level: LanguageLevel


class ProfileOut(BaseModel):
    target_role: str
    seniority: Seniority
    total_years_coding: float
    stacks: list[StackOut]
    languages: list[LanguageOut]
    notable_facts: list[str]
