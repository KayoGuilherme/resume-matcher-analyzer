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
from app.jobs.router import get_job_background_service_factory, get_job_service
from app.jobs.service import JobService
from app.main import create_app
from tests.fixtures.job_postings import ENGLISH
from tests.jobs.fakes import FakeJobRepository
from tests.jobs.support import job_from, stored_job


@dataclass
class Env:
    client: httpx.AsyncClient
    repository: FakeJobRepository
    app: FastAPI

    def add(self, status: str = "uploaded") -> uuid.UUID:
        job = job_from(ENGLISH, status)
        self.repository.by_id[job.id] = job
        return job.id


@pytest.fixture
def make_env() -> Callable[..., Env]:
    def make(*llm_answers: object) -> Env:
        settings = Settings(database_url="postgresql+asyncpg://u:p@localhost:5432/x")
        app = create_app()
        repository = FakeJobRepository()
        service = JobService(repository)  # type: ignore[arg-type]
        llm = FakeLLMClient(list(llm_answers))  # type: ignore[arg-type]

        @asynccontextmanager
        async def factory() -> AsyncIterator[JobService]:
            yield service

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_job_service] = lambda: service
        app.dependency_overrides[get_job_background_service_factory] = lambda: factory
        app.dependency_overrides[get_llm_client] = lambda: llm
        app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient(8)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        return Env(client, repository, app)

    return make


def _body(**override: object) -> dict[str, object]:
    values: dict[str, object] = {"title": "Backend", "description": "Build APIs. Python required."}
    values.update(override)
    return values


# --- create, list, read, delete -----------------------------------------------------------------


async def test_create_with_every_field(make_env: Callable[..., Env]) -> None:
    async with make_env().client as client:
        response = await client.post(
            "/jobs",
            json=_body(company="ACME", requirements_text="- Python"),
        )

    body = response.json()
    assert response.status_code == 201
    assert (body["title"], body["company"], body["requirements_text"]) == (
        "Backend",
        "ACME",
        "- Python",
    )
    assert body["description"] == "Build APIs. Python required."
    assert (body["status"], body["error"], body["extraction"]) == ("uploaded", None, None)
    assert set(body) == {
        "id",
        "title",
        "company",
        "status",
        "error",
        "created_at",
        "description",
        "requirements_text",
        "extraction",
    }


async def test_create_with_only_the_required_fields(make_env: Callable[..., Env]) -> None:
    async with make_env().client as client:
        response = await client.post("/jobs", json=_body())

    assert response.status_code == 201
    assert response.json()["company"] is None and response.json()["requirements_text"] is None


async def test_blank_optional_fields_are_stored_as_null(make_env: Callable[..., Env]) -> None:
    async with make_env().client as client:
        body = (await client.post("/jobs", json=_body(company="  ", requirements_text=""))).json()

    assert body["company"] is None and body["requirements_text"] is None


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"description": None}, "description"),
        ({"title": "   "}, "title"),
        ({"title": "x" * 201}, "title"),
        ({"description": "x" * 50_001}, "description"),
        ({"requirements_text": "x" * 50_001}, "requirements_text"),
        ({"salary": 1}, "salary"),
    ],
)
async def test_invalid_input_is_a_422_naming_the_field(
    make_env: Callable[..., Env], override: dict[str, object], field: str
) -> None:
    async with make_env().client as client:
        response = await client.post("/jobs", json=_body(**override))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error" and field in error["message"]


async def test_a_description_of_exactly_the_limit_is_accepted(
    make_env: Callable[..., Env],
) -> None:
    async with make_env().client as client:
        response = await client.post("/jobs", json=_body(description="x" * 50_000))

    assert response.status_code == 201


async def test_rejected_text_is_not_echoed(make_env: Callable[..., Env]) -> None:
    posting_marker = "SECRET-POSTING-TEXT"
    async with make_env().client as client:
        response = await client.post(
            "/jobs", json=_body(title="", description=posting_marker, extra=posting_marker)
        )

    assert response.status_code == 422
    assert posting_marker not in response.text


async def test_the_same_posting_twice_makes_two_jobs(make_env: Callable[..., Env]) -> None:
    async with make_env().client as client:
        first = await client.post("/jobs", json=_body())
        second = await client.post("/jobs", json=_body())
        listing = (await client.get("/jobs")).json()

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["id"] != second.json()["id"]
    assert len(listing) == 2


async def test_the_list_is_newest_first_without_the_texts(make_env: Callable[..., Env]) -> None:
    env = make_env()
    older = stored_job().model_copy(
        update={"created_at": stored_job().created_at.replace(year=2025)}
    )
    newer = stored_job()
    env.repository.by_id |= {older.id: older, newer.id: newer}

    async with env.client as client:
        listing = (await client.get("/jobs")).json()

    assert [item["id"] for item in listing] == [str(newer.id), str(older.id)]
    for item in listing:
        assert {"description", "requirements_text", "extraction"}.isdisjoint(item)
        assert set(item) == {"id", "title", "company", "status", "error", "created_at"}


async def test_an_empty_list(make_env: Callable[..., Env]) -> None:
    async with make_env().client as client:
        response = await client.get("/jobs")

    assert (response.status_code, response.json()) == (200, [])


async def test_read_round_trip(make_env: Callable[..., Env]) -> None:
    async with make_env().client as client:
        created = (await client.post("/jobs", json=_body(company="ACME"))).json()
        fetched = (await client.get(f"/jobs/{created['id']}")).json()

    assert fetched == created


@pytest.mark.parametrize("method", ["get", "delete", "post_process"])
async def test_unknown_ids_are_404_job_not_found(make_env: Callable[..., Env], method: str) -> None:
    url = f"/jobs/{uuid.uuid4()}"
    async with make_env().client as client:
        response = (
            await client.post(f"{url}/process")
            if method == "post_process"
            else await getattr(client, method)(url)
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


@pytest.mark.parametrize("method", ["get", "delete"])
async def test_a_malformed_id_is_a_validation_error(
    make_env: Callable[..., Env], method: str
) -> None:
    async with make_env().client as client:
        response = await getattr(client, method)("/jobs/not-a-uuid")
        processed = await client.post("/jobs/not-a-uuid/process")

    assert (response.status_code, processed.status_code) == (422, 422)


async def test_delete_and_delete_twice(make_env: Callable[..., Env]) -> None:
    env = make_env()
    job_id = env.add()

    async with env.client as client:
        first = await client.delete(f"/jobs/{job_id}")
        read = await client.get(f"/jobs/{job_id}")
        second = await client.delete(f"/jobs/{job_id}")

    assert (first.status_code, read.status_code, second.status_code) == (204, 404, 404)


# --- processing -----------------------------------------------------------------------------------


async def test_process_returns_202_processing_and_the_result_is_readable_afterwards(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(*ENGLISH.answers)
    job_id = env.add()

    async with env.client:
        response = await env.client.post(f"/jobs/{job_id}/process")
        fetched = (await env.client.get(f"/jobs/{job_id}")).json()

    assert response.status_code == 202
    assert response.json()["status"] == "processing" and response.json()["extraction"] is None
    assert fetched["status"] == "ready" and fetched["error"] is None
    extraction = fetched["extraction"]
    assert extraction["prompt_name"] == "job_extraction"
    assert extraction["llm_model"] == "fake-model"
    assert len(extraction["job"]["requirements"]) == len(ENGLISH.requirements)
    assert extraction["job"]["requirements"][0]["priority"] == "must_have"


async def test_a_job_that_is_processing_is_a_409(make_env: Callable[..., Env]) -> None:
    env = make_env()
    job_id = env.add(status="processing")

    async with env.client:
        response = await env.client.post(f"/jobs/{job_id}/process")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_processing"


async def test_two_overlapping_requests_start_exactly_one_run(
    make_env: Callable[..., Env],
) -> None:
    env = make_env()
    job_id = env.add()

    class SlowLLM(FakeLLMClient):
        async def generate_structured(self, prompt, schema, *, system=None):  # type: ignore[no-untyped-def, override]
            await asyncio.sleep(0.05)  # still running when the second request arrives
            return await super().generate_structured(prompt, schema, system=system)

    slow = SlowLLM(list(ENGLISH.answers))  # type: ignore[arg-type]
    env.app.dependency_overrides[get_llm_client] = lambda: slow

    async with env.client:
        first, second = await asyncio.gather(
            env.client.post(f"/jobs/{job_id}/process"), env.client.post(f"/jobs/{job_id}/process")
        )

    assert sorted([first.status_code, second.status_code]) == [202, 409]


async def test_missing_ai_configuration_is_a_503_and_leaves_the_status(
    make_env: Callable[..., Env],
) -> None:
    env = make_env()
    job_id = env.add()

    def not_configured() -> None:
        raise AINotConfiguredError("No LLM is configured. Set LLM_PROVIDER.")

    env.app.dependency_overrides[get_llm_client] = not_configured

    async with env.client:
        response = await env.client.post(f"/jobs/{job_id}/process")
        status = (await env.client.get(f"/jobs/{job_id}")).json()["status"]

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_not_configured"
    assert status == "uploaded"


async def test_a_failing_run_ends_failed_with_its_code(make_env: Callable[..., Env]) -> None:
    env = make_env(LLMAuthError("status 401"))
    job_id = env.add()

    async with env.client:
        await env.client.post(f"/jobs/{job_id}/process")
        fetched = (await env.client.get(f"/jobs/{job_id}")).json()

    assert fetched["status"] == "failed"
    assert fetched["error"]["code"] == "llm_auth_failed"
    assert fetched["extraction"] is None


async def test_a_failed_job_can_be_processed_again(make_env: Callable[..., Env]) -> None:
    env = make_env(LLMAuthError("status 401"), *ENGLISH.answers)
    job_id = env.add()

    async with env.client:
        await env.client.post(f"/jobs/{job_id}/process")
        again = await env.client.post(f"/jobs/{job_id}/process")
        fetched = (await env.client.get(f"/jobs/{job_id}")).json()

    assert again.status_code == 202
    assert fetched["status"] == "ready" and fetched["error"] is None


async def test_a_failed_reprocess_keeps_the_earlier_extraction(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(*ENGLISH.answers, LLMAuthError("status 401"))
    job_id = env.add()

    async with env.client:
        await env.client.post(f"/jobs/{job_id}/process")
        await env.client.post(f"/jobs/{job_id}/process")
        fetched = (await env.client.get(f"/jobs/{job_id}")).json()

    assert fetched["status"] == "failed" and fetched["extraction"] is not None
