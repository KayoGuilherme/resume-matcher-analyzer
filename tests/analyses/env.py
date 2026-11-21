"""A ready resume, a ready job and a profile in memory, with the analysis service on top."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.ai.embeddings.fake import FakeEmbeddingClient
from app.ai.llm.fake import FakeLLMClient
from app.ai.pipeline import process_job_text, process_resume_text
from app.analyses.service import AnalysisService
from app.core.config import Settings
from app.profile.schemas import LanguageOut, ProfileOut, StackOut
from tests.ai.extraction.builders import RESUME_TEXT, experience, extracted
from tests.analyses.fakes import (
    AnswerAllLLM,
    ConstantEmbeddingClient,
    FakeAnalysisRepository,
    FakeProfileRepository,
)
from tests.fixtures.job_postings import ENGLISH
from tests.jobs.fakes import FakeJobRepository
from tests.jobs.support import job_from
from tests.resumes.fakes import FakeRepository as FakeResumeRepository
from tests.resumes.processing import stored_resume

NOW = datetime(2026, 11, 22, tzinfo=UTC)
BULLET = "Reduced p95 latency by 40%"
PROFILE_FACT = "Built the payments platform of a fintech"

type Embedder = FakeEmbeddingClient | ConstantEmbeddingClient


def a_profile(**overrides: object) -> ProfileOut:
    values: dict[str, object] = {
        "target_role": "Backend Developer",
        "seniority": "senior",
        "total_years_coding": 8,
        "stacks": [
            StackOut(
                name="python", original_name="Python", years=6, level="expert", last_year_used=None
            )
        ],
        "languages": [LanguageOut(name="english", original_name="English", level="C1")],
        "notable_facts": [PROFILE_FACT],
    }
    values.update(overrides)
    return ProfileOut.model_validate(values)


@dataclass
class Env:
    analyses: FakeAnalysisRepository
    resumes: FakeResumeRepository
    jobs: FakeJobRepository
    profiles: FakeProfileRepository
    settings: Settings
    resume_id: uuid.UUID
    job_id: uuid.UUID
    service: AnalysisService = field(init=False)

    def __post_init__(self) -> None:
        self.service = AnalysisService(
            self.analyses,  # type: ignore[arg-type]
            self.resumes,  # type: ignore[arg-type]
            self.jobs,  # type: ignore[arg-type]
            self.profiles,  # type: ignore[arg-type]
            self.settings,
        )

    async def process_resume(self, embedder: Embedder | None = None) -> None:
        """(Re)process the resume: a new extraction, new chunks."""
        llm = FakeLLMClient([extracted(experiences=[experience(BULLET)], skills=["Python, SQL"])])
        processed = await process_resume_text(
            RESUME_TEXT, llm, embedder or ConstantEmbeddingClient(), NOW
        )
        await self.resumes.begin_processing(self.resume_id)
        await self.resumes.save_processed(self.resume_id, processed)

    async def process_job(self, embedder: Embedder | None = None) -> None:
        llm = FakeLLMClient(list(ENGLISH.answers))
        processed = await process_job_text(
            ENGLISH.text, llm, embedder or ConstantEmbeddingClient(), NOW
        )
        await self.jobs.begin_processing(self.job_id)
        await self.jobs.save_processed(self.job_id, processed)


async def make_env(embedder: Embedder | None = None, **settings_overrides: object) -> Env:
    resumes, jobs = FakeResumeRepository(), FakeJobRepository()
    resume, job = stored_resume(), job_from(ENGLISH)
    await resumes.add(resume)
    jobs.by_id[job.id] = job
    settings = Settings.model_validate(
        {"database_url": "postgresql+asyncpg://u:p@localhost/x", **settings_overrides}
    )
    env = Env(
        analyses=FakeAnalysisRepository(),
        resumes=resumes,
        jobs=jobs,
        profiles=FakeProfileRepository(a_profile()),
        settings=settings,
        resume_id=resume.id,
        job_id=job.id,
    )
    await env.process_resume(embedder)
    await env.process_job(embedder)
    return env


def judge() -> AnswerAllLLM:
    return AnswerAllLLM()
