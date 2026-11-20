"""HTTP layer for the candidate profile."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.profile.repository import ProfileRepository
from app.profile.schemas import ProfileIn, ProfileOut
from app.profile.service import ProfileService

router = APIRouter(tags=["profile"])


def get_profile_service(session: Annotated[AsyncSession, Depends(get_session)]) -> ProfileService:
    return ProfileService(ProfileRepository(session))


ServiceDep = Annotated[ProfileService, Depends(get_profile_service)]


@router.put("/profile", response_model=ProfileOut)
async def put_profile(data: ProfileIn, service: ServiceDep) -> ProfileOut:
    """Create or replace the candidate profile."""
    return await service.save(data)


@router.get("/profile", response_model=ProfileOut)
async def get_profile(service: ServiceDep) -> ProfileOut:
    """Return the candidate profile (404 when none was saved)."""
    return await service.get()
