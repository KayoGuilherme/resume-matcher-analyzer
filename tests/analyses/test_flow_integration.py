"""The whole flow against a real PostgreSQL with pgvector: profile, resume, job, analysis,
cache, deletion. Fakes stand in for the LLM and the embeddings."""

import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import text

from app.ai.embeddings import get_embedding_client
from app.ai.extraction.job_models import ExtractedJob
from app.ai.extraction.models import ExtractedResume
from app.ai.llm import get_llm_client
from app.ai.matching.models import JudgeAnswer, JudgeBatch
from app.analyses.repository import AnalysisRepository
from app.analyses.router import get_analysis_background_service_factory
from app.analyses.service import AnalysisService
from app.core.config import Settings, get_settings
from app.core.db import get_engine, get_sessionmaker
from app.jobs.repository import JobRepository
from app.jobs.router import get_job_background_service_factory
from app.jobs.service import JobService
from app.main import create_app
from app.profile.repository import ProfileRepository
from app.resumes.repository import ResumeRepository
from app.resumes.router import get_background_service_factory
from app.resumes.service import ResumeService
from tests.ai.extraction.builders import experience, extracted
from tests.analyses.fakes import ConstantEmbeddingClient
from tests.fixtures import documents
from tests.fixtures.job_postings import ENGLISH

pytestmark = pytest.mark.integration

PDF_BULLET = "Mentored four junior developers and led weekly code reviews for the whole team."
PROFILE = {
    "target_role": "Backend Developer",
    "seniority": "senior",
    "total_years_coding": 8,
    "stacks": [{"name": "Python", "years": 6, "level": "expert"}],
    "languages": [{"name": "English", "level": "C1"}],
    "notable_facts": ["Built the payments platform of a fintech"],
}


class RoutedLLM:
    """Answers each kind of request: resume extraction, job extraction and the judge (`missing`
    for every requirement it is asked about)."""

    provider = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.judge_calls = 0
        self._job_answers = list(ENGLISH.answers)

    async def generate_structured[T: BaseModel](
        self, prompt: str, schema: type[T], *, system: str | None = None
    ) -> T:
        if schema is ExtractedResume:
            return schema.model_validate(
                extracted(
                    experiences=[experience(PDF_BULLET)], skills=["Backend Developer"]
                ).model_dump()
            )
        if schema is ExtractedJob:
            answer = (
                self._job_answers.pop(0) if len(self._job_answers) > 1 else self._job_answers[0]
            )
            return schema.model_validate(answer.model_dump())
        self.judge_calls += 1
        import re

        numbers = [int(n) for n in re.findall(r"\[R(\d+)\]", prompt)]
        answers = [
            JudgeAnswer(requirement=n, verdict="missing", quotes=[], explanation="Not shown.")
            for n in numbers
        ]
        return schema.model_validate(JudgeBatch(answers=answers).model_dump())


@pytest.fixture
async def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[Settings]:
    if not os.environ.get("DATABASE_URL"):
        pytest.fail("DATABASE_URL must be set for integration tests")
    monkeypatch.setenv("RESUME_STORAGE_DIR", str(tmp_path / "files"))
    get_settings.cache_clear()
    current = get_settings()
    engine = get_engine(current)

    async def clear() -> None:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM analysis"))
            await connection.execute(text("DELETE FROM resume"))
            await connection.execute(text("DELETE FROM job"))
            await connection.execute(text("DELETE FROM candidate_profile"))

    await clear()
    yield current
    await clear()
    await engine.dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


async def test_the_whole_flow_from_the_profile_to_the_cached_analysis(
    settings: Settings,
) -> None:
    app = create_app()
    llm = RoutedLLM()

    @asynccontextmanager
    async def resume_factory() -> AsyncIterator[ResumeService]:
        async with get_sessionmaker(settings)() as session:
            yield ResumeService(ResumeRepository(session), None, 1)  # type: ignore[arg-type]

    @asynccontextmanager
    async def job_factory() -> AsyncIterator[JobService]:
        async with get_sessionmaker(settings)() as session:
            yield JobService(JobRepository(session))

    @asynccontextmanager
    async def analysis_factory() -> AsyncIterator[AnalysisService]:
        async with get_sessionmaker(settings)() as session:
            yield AnalysisService(
                AnalysisRepository(session),
                ResumeRepository(session),
                JobRepository(session),
                ProfileRepository(session),
                settings,
            )

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_embedding_client] = lambda: ConstantEmbeddingClient(1024, "const")
    app.dependency_overrides[get_background_service_factory] = lambda: resume_factory
    app.dependency_overrides[get_job_background_service_factory] = lambda: job_factory
    app.dependency_overrides[get_analysis_background_service_factory] = lambda: analysis_factory

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        before_profile = await client.post(
            "/analyses", json={"resume_id": str(uuid.uuid4()), "job_id": str(uuid.uuid4())}
        )
        assert await client.put("/profile", json=PROFILE) is not None
        pdf = documents.clean_pdf()
        resume = (
            await client.post("/resumes", files={"file": ("cv.pdf", pdf, "application/pdf")})
        ).json()
        job = (
            await client.post("/jobs", json={"title": "Backend", "description": ENGLISH.text})
        ).json()
        not_ready = await client.post(
            "/analyses", json={"resume_id": resume["id"], "job_id": job["id"]}
        )
        await client.post(f"/resumes/{resume['id']}/process")
        await client.post(f"/jobs/{job['id']}/process")
        body = {"resume_id": resume["id"], "job_id": job["id"]}

        started = await client.post("/analyses", json=body)
        analysis = (await client.get(f"/analyses/{started.json()['id']}")).json()
        calls = llm.judge_calls
        cached = await client.post("/analyses", json=body)
        calls_after_cache = llm.judge_calls

        await client.put("/profile", json={**PROFILE, "notable_facts": ["A different fact"]})
        fresh = await client.post("/analyses", json=body)

        job_detail = (await client.get(f"/jobs/{job['id']}")).json()
        await client.delete(f"/resumes/{resume['id']}")
        gone = [await client.get(f"/analyses/{a['id']}") for a in (started.json(), fresh.json())]

    assert before_profile.status_code == 404  # an unknown resume, whatever else is missing
    assert not_ready.status_code == 409 and not_ready.json()["error"]["code"] == "resume_not_ready"
    assert started.status_code == 202 and started.json()["status"] == "processing"
    assert analysis["status"] == "ready" and analysis["error"] is None
    requirements = job_detail["extraction"]["job"]["requirements"]
    findings = analysis["result"]["findings"]
    assert len(findings) == len(requirements) > 0
    assert [f["requirement_text"] for f in findings] == [r["text"] for r in requirements]
    assert {f["verdict"] for f in findings} <= {
        "met", "partial", "missing", "in_profile_not_in_resume",
    }  # fmt: skip
    assert (
        analysis["result"]["ats_coverage"]["found"] or analysis["result"]["ats_coverage"]["missing"]
    )
    assert cached.status_code == 200 and cached.json()["id"] == started.json()["id"]
    assert calls_after_cache == calls
    assert fresh.status_code == 202 and fresh.json()["id"] != started.json()["id"]
    assert [response.status_code for response in gone] == [404, 404]
