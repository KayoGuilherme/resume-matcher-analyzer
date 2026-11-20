"""Database access for the candidate profile. No business rules."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.profile.models import PROFILE_ID, CandidateProfile
from app.profile.schemas import ProfileOut


class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> ProfileOut | None:
        """Return the stored profile, or None when none was saved yet."""
        row = await self._session.get(CandidateProfile, PROFILE_ID)
        if row is None:
            return None
        return ProfileOut.model_validate(
            {
                "target_role": row.target_role,
                "seniority": row.seniority,
                "total_years_coding": row.total_years_coding,
                "stacks": row.stacks,
                "languages": row.languages,
                "notable_facts": row.notable_facts,
            }
        )

    async def save(self, profile: ProfileOut) -> None:
        """Create or replace the profile in one atomic statement, then commit."""
        values = profile.model_dump(mode="json")
        statement = insert(CandidateProfile).values(id=PROFILE_ID, **values)
        statement = statement.on_conflict_do_update(index_elements=["id"], set_=values)
        await self._session.execute(statement)
        await self._session.commit()
