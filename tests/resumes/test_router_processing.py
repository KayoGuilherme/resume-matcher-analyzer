import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI

from app.ai.embeddings import get_embedding_client
from app.ai.embeddings.fake import FakeEmbeddingClient
from app.ai.errors import AINotConfiguredError
from app.ai.llm import get_llm_client
from app.ai.llm.base import LLMAuthError
from app.ai.llm.fake import FakeLLMClient
from app.core.config import Settings, get_settings
from app.main import create_app
from app.resumes.router import get_background_service_factory, get_resume_service
from app.resumes.service import ResumeService
from tests.ai.extraction.builders import experience, extracted
from tests.resumes.fakes import FakeRepository, FakeStorage
from tests.resumes.processing import stored_resume

GOOD = "Reduced p95 latency by 40%"


@dataclass
class Env:
    client: httpx.AsyncClient
    repository: FakeRepository
    app: FastAPI

    def add(self, status: str = "uploaded") -> uuid.UUID:
        resume = stored_resume(status=status)
        self.repository.by_id[resume.id] = resume
        return resume.id


@pytest.fixture
def make_env() -> Callable[..., Env]:
    def make(*llm_answers: object) -> Env:
        settings = Settings(database_url="postgresql+asyncpg://u:p@localhost:5432/x")
        app = create_app()
        repository = FakeRepository()
        service = ResumeService(repository, FakeStorage(), 5 * 1024 * 1024)  # type: ignore[arg-type]
        llm = FakeLLMClient(list(llm_answers))  # type: ignore[arg-type]

        @asynccontextmanager
        async def factory() -> AsyncIterator[ResumeService]:
            yield service

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_resume_service] = lambda: service
        app.dependency_overrides[get_background_service_factory] = lambda: factory
        app.dependency_overrides[get_llm_client] = lambda: llm
        app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient(8)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        return Env(client, repository, app)

    return make


def _answer() -> object:
    return extracted(experiences=[experience(GOOD)], skills=["Cloud: AWS, Docker"])


async def test_process_returns_202_processing_and_the_result_is_readable_afterwards(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(_answer())
    resume_id = env.add()

    async with env.client:
        response = await env.client.post(f"/resumes/{resume_id}/process")
        fetched = (await env.client.get(f"/resumes/{resume_id}")).json()

    assert response.status_code == 202
    assert response.json()["status"] == "processing"
    assert response.json()["extraction"] is None
    assert fetched["status"] == "ready"
    assert fetched["error"] is None
    assert fetched["extraction"]["total_experience_months"] == 24
    assert fetched["extraction"]["prompt_name"] == "resume_extraction"
    assert fetched["extraction"]["llm_model"] == "fake-model"


async def test_an_unknown_resume_is_404(make_env: Callable[..., Env]) -> None:
    env = make_env()

    async with env.client:
        response = await env.client.post(f"/resumes/{uuid.uuid4()}/process")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resume_not_found"


async def test_a_resume_that_is_processing_is_a_409(make_env: Callable[..., Env]) -> None:
    env = make_env()
    resume_id = env.add(status="processing")

    async with env.client:
        response = await env.client.post(f"/resumes/{resume_id}/process")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_processing"


async def test_a_malformed_id_is_a_validation_error(make_env: Callable[..., Env]) -> None:
    async with make_env().client as client:
        response = await client.post("/resumes/not-a-uuid/process")

    assert response.status_code == 422


async def test_two_simultaneous_requests_start_exactly_one_run(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(_answer())
    resume_id = env.add()

    class SlowLLM(FakeLLMClient):
        async def generate_structured(self, prompt, schema, *, system=None):  # type: ignore[no-untyped-def, override]
            await asyncio.sleep(0.05)  # the run is still going when the second request arrives
            return await super().generate_structured(prompt, schema, system=system)

    slow = SlowLLM([_answer()])  # type: ignore[list-item]
    env.app.dependency_overrides[get_llm_client] = lambda: slow

    async with env.client:
        first, second = await asyncio.gather(
            env.client.post(f"/resumes/{resume_id}/process"),
            env.client.post(f"/resumes/{resume_id}/process"),
        )

    assert sorted([first.status_code, second.status_code]) == [202, 409]


async def test_missing_ai_configuration_is_a_503_and_leaves_the_status(
    make_env: Callable[..., Env],
) -> None:
    env = make_env()
    resume_id = env.add()

    def not_configured() -> None:
        raise AINotConfiguredError("No LLM is configured. Set LLM_PROVIDER.")

    env.app.dependency_overrides[get_llm_client] = not_configured

    async with env.client:
        response = await env.client.post(f"/resumes/{resume_id}/process")
        status = (await env.client.get(f"/resumes/{resume_id}")).json()["status"]

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_not_configured"
    assert status == "uploaded"


async def test_a_failing_run_ends_failed_with_the_error_code(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(LLMAuthError("status 401"))
    resume_id = env.add()

    async with env.client:
        await env.client.post(f"/resumes/{resume_id}/process")
        fetched = (await env.client.get(f"/resumes/{resume_id}")).json()

    assert fetched["status"] == "failed"
    assert fetched["error"]["code"] == "llm_auth_failed"
    assert fetched["extraction"] is None


async def test_a_failed_resume_can_be_processed_again(make_env: Callable[..., Env]) -> None:
    env = make_env(LLMAuthError("status 401"), _answer())
    resume_id = env.add()

    async with env.client:
        await env.client.post(f"/resumes/{resume_id}/process")
        again = await env.client.post(f"/resumes/{resume_id}/process")
        fetched = (await env.client.get(f"/resumes/{resume_id}")).json()

    assert again.status_code == 202
    assert fetched["status"] == "ready"
    assert fetched["error"] is None


async def test_a_failed_reprocess_keeps_the_earlier_extraction(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(_answer(), LLMAuthError("status 401"))
    resume_id = env.add()

    async with env.client:
        await env.client.post(f"/resumes/{resume_id}/process")
        await env.client.post(f"/resumes/{resume_id}/process")
        fetched = (await env.client.get(f"/resumes/{resume_id}")).json()

    assert fetched["status"] == "failed"
    assert fetched["extraction"] is not None


async def test_the_list_shows_the_status_without_text_or_extraction(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(_answer())
    resume_id = env.add()

    async with env.client:
        await env.client.post(f"/resumes/{resume_id}/process")
        listing = (await env.client.get("/resumes")).json()

    (item,) = listing
    assert item["status"] == "ready"
    assert "text" not in item and "extraction" not in item
