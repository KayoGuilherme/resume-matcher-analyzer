"""HTTP layer for gap analyses."""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import LLMClient, get_llm_client
from app.ai.matching.markdown import render_markdown
from app.ai.matching.report_models import Report
from app.analyses.repository import AnalysisRepository
from app.analyses.schemas import AnalysisDetail, AnalysisRequest
from app.analyses.service import AnalysisService
from app.core.config import Settings, get_settings
from app.core.db import get_session, get_sessionmaker
from app.jobs.repository import JobRepository
from app.profile.repository import ProfileRepository
from app.resumes.repository import ResumeRepository

router = APIRouter(tags=["analyses"])


def _service(session: AsyncSession, settings: Settings) -> AnalysisService:
    return AnalysisService(
        AnalysisRepository(session),
        ResumeRepository(session),
        JobRepository(session),
        ProfileRepository(session),
        settings,
    )


def get_analysis_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalysisService:
    return _service(session, settings)


ServiceDep = Annotated[AnalysisService, Depends(get_analysis_service)]
ServiceFactory = Callable[[], AbstractAsyncContextManager[AnalysisService]]


def get_analysis_background_service_factory(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ServiceFactory:
    """Background work runs after the response, when the request's session is closed, so it
    opens its own."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AnalysisService]:
        async with get_sessionmaker(settings)() as session:
            yield _service(session, settings)

    return factory


async def _run_in_background(
    factory: ServiceFactory, analysis_id: uuid.UUID, llm: LLMClient
) -> None:
    async with factory() as service:
        await service.run(analysis_id, llm)


@router.post("/analyses", response_model=AnalysisDetail, status_code=202)
async def create_analysis(
    data: AnalysisRequest,
    response: Response,
    background: BackgroundTasks,
    service: ServiceDep,
    factory: Annotated[ServiceFactory, Depends(get_analysis_background_service_factory)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> AnalysisDetail:
    """Compare a ready resume with a ready job (the profile must exist).

    202 with status `processing` when a new analysis starts in the background (or one for the
    same inputs is still running), 200 with the stored analysis when one for the same inputs is
    already `ready`. The LLM client is a dependency, so a missing configuration answers 503
    before anything is stored. Poll `GET /analyses/{id}` for `ready` or `failed`.
    """
    analysis, started = await service.request(data.resume_id, data.job_id, llm)
    if started:
        background.add_task(_run_in_background, factory, analysis.id, llm)
    elif analysis.status == "ready":
        response.status_code = 200
    return analysis


@router.get("/analyses/{analysis_id}", response_model=AnalysisDetail)
async def get_analysis(analysis_id: uuid.UUID, service: ServiceDep) -> AnalysisDetail:
    return await service.get(analysis_id)


@router.get("/analyses/{analysis_id}/report", response_model=Report)
async def get_report(
    analysis_id: uuid.UUID,
    service: ServiceDep,
    format: Literal["json", "markdown"] = "json",  # noqa: A002 - the public query parameter
) -> Report | Response:
    """The screening report of a `ready` analysis: the score and outcome, the simulated
    screener, prioritized actions and rewrite suggestions, always with the disclaimer. JSON by
    default, Markdown with `?format=markdown`. No provider is called: the score follows the
    `SCORE_*` settings in force when it is read."""
    report = await service.get_report(analysis_id)
    if format == "markdown":
        return Response(render_markdown(report), media_type="text/markdown; charset=utf-8")
    return report
