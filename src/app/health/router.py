"""Health endpoint: app status plus database connectivity."""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session

logger = logging.getLogger(__name__)

DB_CHECK_TIMEOUT_SECONDS = 2.0

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    database: str


@router.get("/health", response_model=HealthResponse)
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> JSONResponse:
    """Report app status; 503 when the database cannot be reached."""
    try:
        await asyncio.wait_for(session.execute(text("SELECT 1")), DB_CHECK_TIMEOUT_SECONDS)
    except Exception as exc:
        # Type only: driver messages can contain connection strings.
        logger.warning("database health check failed", extra={"exception_type": type(exc).__name__})
        body = HealthResponse(status="degraded", database="unavailable")
        return JSONResponse(status_code=503, content=body.model_dump())
    return JSONResponse(content=HealthResponse(status="ok", database="ok").model_dump())
