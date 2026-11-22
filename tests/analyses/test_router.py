import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI

from app.ai.errors import AINotConfiguredError
from app.ai.llm import get_llm_client
from app.ai.llm.base import LLMTimeoutError
from app.ai.llm.fake import FakeLLMClient
from app.analyses.router import get_analysis_background_service_factory, get_analysis_service
from app.analyses.service import AnalysisService
from app.core.config import get_settings
from app.main import create_app
from tests.ai.extraction.builders import RESUME_TEXT
from tests.analyses.env import BULLET, Env, make_env
from tests.analyses.fakes import AnswerAllLLM
from tests.fixtures.job_postings import ENGLISH


@dataclass
class Api:
    client: httpx.AsyncClient
    env: Env
    llm: AnswerAllLLM
    app: FastAPI

    async def post(self, **override: object) -> httpx.Response:
        body: dict[str, object] = {
            "resume_id": str(self.env.resume_id),
            "job_id": str(self.env.job_id),
        }
        body.update(override)
        return await self.client.post("/analyses", json=body)


@pytest.fixture
def make_api() -> Callable[..., object]:
    async def make(llm: object = None) -> Api:
        env = await make_env()
        judge = llm or AnswerAllLLM()
        app = create_app()
        service: AnalysisService = env.service

        @asynccontextmanager
        async def factory() -> AsyncIterator[AnalysisService]:
            yield service

        app.dependency_overrides[get_settings] = lambda: env.settings
        app.dependency_overrides[get_analysis_service] = lambda: service
        app.dependency_overrides[get_analysis_background_service_factory] = lambda: factory
        app.dependency_overrides[get_llm_client] = lambda: judge
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        return Api(client, env, judge, app)  # type: ignore[arg-type]

    return make


async def test_a_new_analysis_is_a_202_with_status_processing(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        response = await api.post()

    body = response.json()
    assert response.status_code == 202 and body["status"] == "processing"
    assert (body["resume_id"], body["job_id"]) == (str(api.env.resume_id), str(api.env.job_id))
    assert body["error"] is None and body["result"] is None
    assert set(body) == {
        "id", "resume_id", "job_id", "status", "error", "created_at", "completed_at", "result",
    }  # fmt: skip


async def test_the_background_work_makes_it_ready_and_the_result_is_readable(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        created = (await api.post()).json()
        fetched = await api.client.get(f"/analyses/{created['id']}")

    body = fetched.json()
    assert fetched.status_code == 200 and body["status"] == "ready"
    assert body["completed_at"] is not None and body["error"] is None
    assert body["result"]["findings"] and "ats_coverage" in body["result"]
    assert body["result"]["provenance"]["prompt_name"] == "gap_judge"


async def test_the_same_request_again_is_a_200_with_the_same_analysis_and_no_llm_call(
    make_api,
) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        first = (await api.post()).json()
        calls = api.llm.calls
        again = await api.post()

    assert again.status_code == 200 and again.json()["id"] == first["id"]
    assert again.json()["status"] == "ready" and api.llm.calls == calls


async def test_the_same_request_while_running_is_a_202_and_starts_nothing(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()
    running, _ = await api.env.service.request(api.env.resume_id, api.env.job_id, api.llm)

    async with api.client:
        response = await api.post()
        status = (await api.client.get(f"/analyses/{running.id}")).json()["status"]

    assert response.status_code == 202 and response.json()["id"] == str(running.id)
    assert status == "processing" and api.llm.calls == 0


async def test_unknown_resume_and_job_are_404s(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        no_resume = await api.post(resume_id=str(uuid.uuid4()))
        no_job = await api.post(job_id=str(uuid.uuid4()))

    assert (no_resume.status_code, no_resume.json()["error"]["code"]) == (404, "resume_not_found")
    assert (no_job.status_code, no_job.json()["error"]["code"]) == (404, "job_not_found")
    assert api.env.analyses.by_id == {}


async def test_each_precondition_is_a_409_with_its_code_and_stores_nothing(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()
    env = api.env
    resume, job = env.resumes.by_id[env.resume_id], env.jobs.by_id[env.job_id]

    async with api.client:
        env.resumes.by_id[env.resume_id] = resume.model_copy(update={"status": "uploaded"})
        first = await api.post()
        env.resumes.by_id[env.resume_id] = resume
        env.jobs.by_id[env.job_id] = job.model_copy(update={"status": "processing"})
        second = await api.post()
        env.jobs.by_id[env.job_id] = job
        env.profiles.profile = None
        third = await api.post()

    assert [r.status_code for r in (first, second, third)] == [409, 409, 409]
    assert [r.json()["error"]["code"] for r in (first, second, third)] == [
        "resume_not_ready",
        "job_not_ready",
        "profile_required",
    ]
    assert "PUT /profile" in third.json()["error"]["message"]
    assert env.analyses.by_id == {}


async def test_different_embedding_models_are_a_409(make_api) -> None:  # type: ignore[no-untyped-def]
    from tests.analyses.fakes import ConstantEmbeddingClient

    api = await make_api()
    await api.env.process_job(ConstantEmbeddingClient(model_name="other"))

    async with api.client:
        response = await api.post()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "embedding_model_mismatch"


async def test_a_missing_llm_configuration_is_a_503_before_any_other_check(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    def not_configured() -> None:
        raise AINotConfiguredError("No LLM is configured. Set LLM_PROVIDER.")

    api.app.dependency_overrides[get_llm_client] = not_configured
    api.env.profiles.profile = None

    async with api.client:
        unknown = await api.post(resume_id=str(uuid.uuid4()))
        no_profile = await api.post()

    for response in (unknown, no_profile):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "ai_not_configured"
    assert api.env.analyses.by_id == {}


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"resume_id": "x"}, "job_id"),
        ({"resume_id": "not-a-uuid", "job_id": "also-not"}, "resume_id"),
        ({"resume_id": str(uuid.uuid4()), "job_id": str(uuid.uuid4()), "force": True}, "force"),
    ],
)
async def test_an_invalid_body_is_a_422_naming_the_field(make_api, body: dict, field: str) -> None:  # type: ignore[no-untyped-def,type-arg]
    api = await make_api()

    async with api.client:
        response = await api.client.post("/analyses", json=body)

    assert response.status_code == 422 and field in response.json()["error"]["message"]


async def test_reading_an_unknown_analysis_is_a_404(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        response = await api.client.get(f"/analyses/{uuid.uuid4()}")
        bad = await api.client.get("/analyses/not-a-uuid")

    assert (response.status_code, response.json()["error"]["code"]) == (404, "analysis_not_found")
    assert bad.status_code == 422


async def test_a_failed_analysis_shows_its_error_and_no_result(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api(FakeLLMClient([LLMTimeoutError("x")]))

    async with api.client:
        created = (await api.post()).json()
        body = (await api.client.get(f"/analyses/{created['id']}")).json()

    assert body["status"] == "failed" and body["result"] is None
    assert body["error"]["code"] == "llm_timeout" and body["error"]["message"]


async def test_the_response_does_not_carry_the_resume_or_job_text(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        created = await api.post()
        fetched = await api.client.get(f"/analyses/{created.json()['id']}")

    for response in (created, fetched):
        assert RESUME_TEXT not in response.text and ENGLISH.text not in response.text
    assert BULLET not in created.text


async def test_the_openapi_lists_the_analyses_routes() -> None:
    paths = create_app().openapi()["paths"]

    assert set(paths["/analyses"]) == {"post"}
    assert set(paths["/analyses/{analysis_id}"]) == {"get"}


# --- GET /analyses/{id}/report ----------------------------------------------------------------


async def _ready_id(api: "Api") -> str:
    created = await api.post()
    await api.client.get(f"/analyses/{created.json()['id']}")  # background work has run
    return str(created.json()["id"])


async def test_the_report_is_json_by_default_and_with_format_json(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        analysis_id = await _ready_id(api)
        default = await api.client.get(f"/analyses/{analysis_id}/report")
        explicit = await api.client.get(f"/analyses/{analysis_id}/report?format=json")

    assert default.status_code == explicit.status_code == 200
    assert default.headers["content-type"].startswith("application/json")
    body = default.json()
    assert body == explicit.json() and body["analysis_id"] == analysis_id
    assert {"disclaimer", "score", "screener", "actions", "suggestions", "provenance"} <= set(body)
    assert "real ATS" in body["disclaimer"]


async def test_the_report_as_markdown(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        analysis_id = await _ready_id(api)
        response = await api.client.get(f"/analyses/{analysis_id}/report?format=markdown")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.text.startswith("# Screening report")
    assert "real ATS" in response.text


async def test_markdown_and_json_agree(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        analysis_id = await _ready_id(api)
        body = (await api.client.get(f"/analyses/{analysis_id}/report")).json()
        text = (await api.client.get(f"/analyses/{analysis_id}/report?format=markdown")).text

    assert f"**{body['score']['value']:g} / 100**" in text
    assert f"`{body['score']['outcome']}`" in text
    assert f"`{body['screener']['decision']}`" in text
    assert f"{body['screener']['consistency']:g}" in text
    import re

    assert len(re.findall(r"^\d+\. ", text, re.MULTILINE)) == len(body["actions"])


async def test_an_unknown_format_is_a_422_naming_the_parameter(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        analysis_id = await _ready_id(api)
        response = await api.client.get(f"/analyses/{analysis_id}/report?format=pdf")

    assert response.status_code == 422
    assert "format" in response.json()["error"]["message"]


async def test_an_unknown_analysis_has_no_report(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        response = await api.client.get(f"/analyses/{uuid.uuid4()}/report")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "analysis_not_found"


async def test_a_running_analysis_has_no_report_yet(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()
    async with api.client:
        analysis, _ = await api.env.service.request(api.env.resume_id, api.env.job_id, api.llm)

        response = await api.client.get(f"/analyses/{analysis.id}/report")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "report_not_ready"


async def test_a_failed_analysis_has_no_report(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api(FakeLLMClient([LLMTimeoutError("slow")]))

    async with api.client:
        analysis_id = await _ready_id(api)
        response = await api.client.get(f"/analyses/{analysis_id}/report")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "analysis_failed"


async def test_an_analysis_without_a_report_is_a_404(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        analysis_id = await _ready_id(api)
        api.env.analyses.reports.pop(uuid.UUID(analysis_id))
        response = await api.client.get(f"/analyses/{analysis_id}/report")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "report_not_available"


async def test_reading_the_report_needs_no_llm_provider(make_api) -> None:  # type: ignore[no-untyped-def]
    api = await make_api()

    async with api.client:
        analysis_id = await _ready_id(api)

        def unavailable() -> object:
            raise AINotConfiguredError("no llm")

        api.app.dependency_overrides[get_llm_client] = unavailable
        calls = api.llm.calls
        response = await api.client.get(f"/analyses/{analysis_id}/report")

    assert response.status_code == 200
    assert api.llm.calls == calls
