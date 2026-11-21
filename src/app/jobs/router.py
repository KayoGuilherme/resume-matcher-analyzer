"""HTTP layer for job positions."""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import EmbeddingClient, get_embedding_client
from app.ai.llm import LLMClient, get_llm_client
from app.core.config import Settings, get_settings
from app.core.db import get_session, get_sessionmaker
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobDetail, JobIn, JobSummary
from app.jobs.service import JobService

router = APIRouter(tags=["jobs"])


def get_job_service(session: Annotated[AsyncSession, Depends(get_session)]) -> JobService:
    return JobService(JobRepository(session))


ServiceDep = Annotated[JobService, Depends(get_job_service)]
ServiceFactory = Callable[[], AbstractAsyncContextManager[JobService]]


def get_job_background_service_factory(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ServiceFactory:
    """Background work runs after the response, when the request's session is closed, so it
    opens its own."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[JobService]:
        async with get_sessionmaker(settings)() as session:
            yield JobService(JobRepository(session))

    return factory


async def _process_in_background(
    factory: ServiceFactory, job_id: uuid.UUID, llm: LLMClient, embedder: EmbeddingClient
) -> None:
    async with factory() as service:
        await service.run_processing(job_id, llm, embedder)


@router.post("/jobs", response_model=JobDetail, status_code=201)
async def create_job(data: JobIn, service: ServiceDep) -> JobDetail:
    """Store a job posting (status `uploaded`). Every post creates a new job."""
    return await service.create(data)


@router.get("/jobs", response_model=list[JobSummary])
async def list_jobs(service: ServiceDep) -> list[JobSummary]:
    """All jobs, newest first, without their texts."""
    return await service.list_all()


@router.get("/jobs/{job_id}", response_model=JobDetail)
async def get_job(job_id: uuid.UUID, service: ServiceDep) -> JobDetail:
    return await service.get(job_id)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: uuid.UUID, service: ServiceDep) -> None:
    await service.delete(job_id)


@router.post("/jobs/{job_id}/process", response_model=JobDetail, status_code=202)
async def process_job(
    job_id: uuid.UUID,
    background: BackgroundTasks,
    service: ServiceDep,
    factory: Annotated[ServiceFactory, Depends(get_job_background_service_factory)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    embedder: Annotated[EmbeddingClient, Depends(get_embedding_client)],
) -> JobDetail:
    """Start extraction and embedding in the background (202, status `processing`).

    The AI clients are dependencies, so a missing configuration answers 503 before anything
    changes. Poll `GET /jobs/{id}` for `ready` or `failed`.
    """
    job = await service.start_processing(job_id)
    background.add_task(_process_in_background, factory, job_id, llm, embedder)
    return job
