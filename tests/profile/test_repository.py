from typing import Any

from sqlalchemy.dialects import postgresql

from app.profile.models import CandidateProfile
from app.profile.repository import ProfileRepository
from app.profile.schemas import LanguageOut, ProfileOut, StackOut


class FakeSession:
    def __init__(self, row: CandidateProfile | None = None) -> None:
        self.row = row
        self.executed: list[Any] = []
        self.commits = 0
        self.requested: tuple[Any, Any] | None = None

    async def get(self, model: Any, key: Any) -> CandidateProfile | None:
        self.requested = (model, key)
        return self.row

    async def execute(self, statement: Any) -> None:
        self.executed.append(statement)

    async def commit(self) -> None:
        self.commits += 1


def _profile() -> ProfileOut:
    return ProfileOut(
        target_role="Backend Developer",
        seniority="senior",
        total_years_coding=8.5,
        stacks=[
            StackOut(
                name="postgresql",
                original_name="Postgres",
                years=5,
                level="expert",
                last_year_used=None,
            )
        ],
        languages=[LanguageOut(name="portuguese", original_name="pt", level="native")],
        notable_facts=["Led a migration"],
    )


def _row(profile: ProfileOut) -> CandidateProfile:
    return CandidateProfile(id=1, **profile.model_dump(mode="json"))


async def test_get_returns_none_when_nothing_is_stored() -> None:
    session = FakeSession()

    assert await ProfileRepository(session).get() is None  # type: ignore[arg-type]
    assert session.requested == (CandidateProfile, 1)


async def test_get_maps_the_stored_row_back_to_the_profile() -> None:
    profile = _profile()
    session = FakeSession(_row(profile))

    assert await ProfileRepository(session).get() == profile  # type: ignore[arg-type]


async def test_save_upserts_the_single_row_and_commits() -> None:
    session = FakeSession()
    profile = _profile()

    await ProfileRepository(session).save(profile)  # type: ignore[arg-type]

    (statement,) = session.executed
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "INSERT INTO candidate_profile" in str(compiled)
    assert "ON CONFLICT (id) DO UPDATE" in str(compiled)
    assert compiled.params["id"] == 1
    assert compiled.params["target_role"] == "Backend Developer"
    assert compiled.params["stacks"] == profile.model_dump(mode="json")["stacks"]
    assert session.commits == 1
