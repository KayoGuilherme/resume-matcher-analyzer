"""HTTP layer for resumes."""

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, Response, UploadFile
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import EmbeddingClient, get_embedding_client
from app.ai.llm import LLMClient, get_llm_client
from app.core.config import Settings, get_settings
from app.core.db import get_session, get_sessionmaker
from app.core.storage import FileStorage, get_file_storage
from app.resumes.repository import ResumeRepository
from app.resumes.schemas import ResumeDetail, ResumeSummary
from app.resumes.service import FileTooLargeError, ResumeService, format_size_limit

MULTIPART_OVERHEAD_BYTES = 64 * 1024  # boundaries and headers around the file in the body


class SizeLimitedRoute(APIRoute):
    """Reject an oversized upload from its Content-Length before the body is read.

    FastAPI reads (and Starlette spools to disk) the whole multipart body before dependencies
    run, so this check has to wrap the route handler. Requests without a Content-Length, or
    lying about it, are still bounded by the `max + 1` read in the endpoint.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            overrides = request.app.dependency_overrides
            settings: Settings = overrides.get(get_settings, get_settings)()
            declared = request.headers.get("content-length", "")
            limit = settings.resume_max_upload_bytes
            if declared.isdigit() and int(declared) > limit + MULTIPART_OVERHEAD_BYTES:
                raise FileTooLargeError(
                    f"The file is larger than the {format_size_limit(limit)} limit for resume "
                    "uploads."
                )
            return await handler(request)

        return guarded


router = APIRouter(tags=["resumes"], route_class=SizeLimitedRoute)


def get_resume_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[FileStorage, Depends(get_file_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ResumeService:
    return ResumeService(ResumeRepository(session), storage, settings.resume_max_upload_bytes)


ServiceDep = Annotated[ResumeService, Depends(get_resume_service)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/resumes",
    response_model=ResumeDetail,
    status_code=201,
    responses={200: {"model": ResumeDetail, "description": "The same file was already stored"}},
)
async def upload_resume(
    file: Annotated[UploadFile, File()],
    service: ServiceDep,
    settings: SettingsDep,
    response: Response,
) -> ResumeDetail:
    """Upload a PDF or DOCX resume (201), or get the existing one for identical bytes (200)."""
    try:
        data = await file.read(settings.resume_max_upload_bytes + 1)
    finally:
        await file.close()
    result = await service.upload(file.filename, data)
    response.status_code = 201 if result.created else 200
    return result.resume


@router.get("/resumes", response_model=list[ResumeSummary])
async def list_resumes(service: ServiceDep) -> list[ResumeSummary]:
    """All resumes, newest first, without their text."""
    return await service.list_all()


@router.get("/resumes/{resume_id}", response_model=ResumeDetail)
async def get_resume(resume_id: uuid.UUID, service: ServiceDep) -> ResumeDetail:
    return await service.get(resume_id)


@router.delete("/resumes/{resume_id}", status_code=204)
async def delete_resume(resume_id: uuid.UUID, service: ServiceDep) -> None:
    await service.delete(resume_id)


ServiceFactory = Callable[[], AbstractAsyncContextManager[ResumeService]]


def get_background_service_factory(
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[FileStorage, Depends(get_file_storage)],
) -> ServiceFactory:
    """Background work runs after the response, when the request's session is closed, so it
    opens its own."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[ResumeService]:
        async with get_sessionmaker(settings)() as session:
            yield ResumeService(
                ResumeRepository(session), storage, settings.resume_max_upload_bytes
            )

    return factory


async def _process_in_background(
    factory: ServiceFactory, resume_id: uuid.UUID, llm: LLMClient, embedder: EmbeddingClient
) -> None:
    async with factory() as service:
        await service.run_processing(resume_id, llm, embedder)


@router.post("/resumes/{resume_id}/process", response_model=ResumeDetail, status_code=202)
async def process_resume(
    resume_id: uuid.UUID,
    background: BackgroundTasks,
    service: ServiceDep,
    factory: Annotated[ServiceFactory, Depends(get_background_service_factory)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    embedder: Annotated[EmbeddingClient, Depends(get_embedding_client)],
) -> ResumeDetail:
    """Start extraction, chunking and embedding in the background (202, status `processing`).

    The AI clients are dependencies, so a missing configuration answers 503 before anything
    changes. Poll `GET /resumes/{id}` for `ready` or `failed`.
    """
    resume = await service.start_processing(resume_id)
    background.add_task(_process_in_background, factory, resume_id, llm, embedder)
    return resume
