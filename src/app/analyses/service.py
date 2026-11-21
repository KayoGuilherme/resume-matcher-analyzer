"""Business rules for gap analyses: the preconditions, the cache, and running the engine."""

import logging
import time
import uuid
from datetime import UTC, datetime

from app.ai.error_codes import processing_error_code
from app.ai.llm.base import LLMClient
from app.ai.matching import judge
from app.ai.matching.cache import cache_key, inputs_fingerprint
from app.ai.matching.engine import analyze
from app.ai.matching.errors import EmbeddingModelMismatchError
from app.ai.matching.models import (
    AnalysisInput,
    AnalysisResult,
    AnalysisSettings,
    JobInput,
    ProfileFacts,
    ProfileLanguage,
    ProfileStack,
    RequirementInput,
    ResumeInput,
)
from app.ai.prompts.loader import load_prompt
from app.analyses.repository import AnalysisRepository
from app.analyses.schemas import AnalysisDetail
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.processing import PROCESSING_MESSAGES
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobDetail
from app.jobs.service import JobNotFoundError
from app.profile.repository import ProfileRepository
from app.profile.schemas import ProfileOut
from app.resumes.repository import ResumeRepository
from app.resumes.schemas import ResumeDetail
from app.resumes.service import ResumeNotFoundError

logger = logging.getLogger(__name__)


class AnalysisNotFoundError(DomainError):
    status_code = 404
    code = "analysis_not_found"


class ResumeNotReadyError(DomainError):
    status_code = 409
    code = "resume_not_ready"


class JobNotReadyError(DomainError):
    status_code = 409
    code = "job_not_ready"


class ProfileRequiredError(DomainError):
    status_code = 409
    code = "profile_required"


class EmbeddingModelsDifferError(DomainError):
    status_code = 409
    code = "embedding_model_mismatch"


def analysis_settings(settings: Settings) -> AnalysisSettings:
    return AnalysisSettings(
        top_k=settings.analysis_top_k,
        min_similarity=settings.analysis_min_similarity,
        max_requirements_per_call=settings.analysis_max_requirements_per_call,
        max_llm_calls=settings.analysis_max_llm_calls,
    )


def _profile_facts(profile: ProfileOut) -> ProfileFacts:
    return ProfileFacts(
        total_years_coding=profile.total_years_coding,
        stacks=[ProfileStack(name=s.name, years=s.years, level=s.level) for s in profile.stacks],
        languages=[ProfileLanguage(name=item.name, level=item.level) for item in profile.languages],
        notable_facts=profile.notable_facts,
    )


def _single_model(models: set[str]) -> str:
    if len(models) > 1:
        raise EmbeddingModelMismatchError("The stored vectors use more than one embedding model")
    return next(iter(models), "")


class AnalysisService:
    def __init__(
        self,
        analyses: AnalysisRepository,
        resumes: ResumeRepository,
        jobs: JobRepository,
        profiles: ProfileRepository,
        settings: Settings,
    ) -> None:
        self._analyses = analyses
        self._resumes = resumes
        self._jobs = jobs
        self._profiles = profiles
        self._settings = analysis_settings(settings)

    async def get(self, analysis_id: uuid.UUID) -> AnalysisDetail:
        analysis = await self._analyses.get(analysis_id)
        if analysis is None:
            raise AnalysisNotFoundError("Analysis not found")
        return analysis

    async def request(
        self, resume_id: uuid.UUID, job_id: uuid.UUID, llm: LLMClient
    ) -> tuple[AnalysisDetail, bool]:
        """Check the preconditions, then return the analysis to use and whether this call
        created it (only then must the work be started). Nothing is stored when a check fails."""
        resume = await self._resumes.get(resume_id)
        if resume is None:
            raise ResumeNotFoundError("Resume not found")
        job = await self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError("Job not found")
        if resume.status != "ready" or resume.extraction is None:
            raise ResumeNotReadyError("The resume is not ready: process it first")
        if job.status != "ready" or job.extraction is None:
            raise JobNotReadyError("The job is not ready: process it first")
        profile = await self._profiles.get()
        if profile is None:
            raise ProfileRequiredError("There is no candidate profile: save it with PUT /profile")

        chunks = await self._resumes.get_chunks(resume_id)
        vectors = await self._jobs.get_requirement_vectors(job_id)
        models = chunks.embedding_models | vectors.embedding_models
        if chunks.chunks and vectors.vectors and len(models) > 1:
            raise EmbeddingModelsDifferError(
                "The resume and the job were embedded with different models: process the older "
                "of the two again"
            )

        key = self._key(
            resume, job, profile, chunks.embedding_models, vectors.embedding_models, llm
        )
        existing = await self._analyses.find_active(key)
        if existing is not None:
            logger.info("analysis reused", extra={"analysis_id": str(existing.id)})
            return existing, False
        new = AnalysisDetail(
            id=uuid.uuid4(),
            resume_id=resume_id,
            job_id=job_id,
            status="processing",
            created_at=datetime.now(UTC),
        )
        analysis, created = await self._analyses.create(new, key)
        logger.info(
            "analysis requested", extra={"analysis_id": str(analysis.id), "started": created}
        )
        return analysis, created

    def _key(
        self,
        resume: ResumeDetail,
        job: JobDetail,
        profile: ProfileOut,
        resume_models: set[str],
        job_models: set[str],
        llm: LLMClient,
    ) -> str:
        prompt = load_prompt(judge.PROMPT_NAME)
        fingerprint = inputs_fingerprint(
            resume_extraction=resume.extraction.model_dump(mode="json")
            if resume.extraction
            else None,
            resume_embedding_model=",".join(sorted(resume_models)),
            job_extraction=job.extraction.model_dump(mode="json") if job.extraction else None,
            job_embedding_model=",".join(sorted(job_models)),
            profile=profile.model_dump(mode="json"),
        )
        return cache_key(
            resume_id=resume.id,
            job_id=job.id,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            llm_provider=llm.provider,
            llm_model=llm.model,
            settings=self._settings,
            fingerprint=fingerprint,
        )

    async def run(self, analysis_id: uuid.UUID, llm: LLMClient) -> None:
        """Run an analysis that is `processing` and store the result.

        Never raises for failures: they end as status `failed` with a safe error.
        """
        started = time.perf_counter()
        try:
            analysis = await self._analyses.get(analysis_id)
            if analysis is None:
                logger.warning("analysis vanished", extra={"analysis_id": str(analysis_id)})
                return
            inputs = await self._load(analysis.resume_id, analysis.job_id)
            if inputs is None:
                logger.warning("analysis inputs vanished", extra={"analysis_id": str(analysis_id)})
                return
            result = await analyze(inputs, llm, self._settings, datetime.now(UTC))
            if not await self._analyses.save_result(analysis_id, result):
                logger.warning(
                    "analysis deleted meanwhile", extra={"analysis_id": str(analysis_id)}
                )
                return
        except Exception as error:
            code = processing_error_code(error)
            logger.warning(
                "analysis failed",
                extra={
                    "analysis_id": str(analysis_id),
                    "error_code": code,
                    "exception_type": type(error).__name__,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                },
            )
            await self._analyses.set_failed(analysis_id, code, PROCESSING_MESSAGES[code])
            return
        _log_finished(analysis_id, result, started)

    async def _load(self, resume_id: uuid.UUID, job_id: uuid.UUID) -> AnalysisInput | None:
        """One snapshot of everything the analysis reads. None when a row is gone."""
        resume = await self._resumes.get(resume_id)
        job = await self._jobs.get(job_id)
        profile = await self._profiles.get()
        if resume is None or job is None:
            return None
        if resume.status != "ready" or resume.extraction is None:
            raise ResumeNotReadyError("The resume is no longer ready")
        if job.status != "ready" or job.extraction is None:
            raise JobNotReadyError("The job is no longer ready")
        if profile is None:
            raise ProfileRequiredError("There is no candidate profile")
        chunks = await self._resumes.get_chunks(resume_id)
        vectors = await self._jobs.get_requirement_vectors(job_id)
        return AnalysisInput(
            resume=ResumeInput(
                text=resume.text,
                resume=resume.extraction.resume,
                chunks=chunks.chunks,
                embedding_model=_single_model(chunks.embedding_models),
            ),
            job=JobInput(
                language=job.extraction.job.language,
                ats_keywords=job.extraction.job.ats_keywords,
                requirements=[
                    RequirementInput(requirement=r, embedding=vectors.vectors[r.id])
                    for r in job.extraction.job.requirements
                ],
                embedding_model=_single_model(vectors.embedding_models),
            ),
            profile=_profile_facts(profile),
        )


def _log_finished(analysis_id: uuid.UUID, result: AnalysisResult, started: float) -> None:
    logger.info(
        "analysis finished",
        extra={
            "analysis_id": str(analysis_id),
            "requirement_count": len(result.findings),
            "llm_calls": result.provenance.llm_calls,
            "duration_ms": round((time.perf_counter() - started) * 1000),
        },
    )
