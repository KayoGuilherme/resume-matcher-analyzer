"""Business rules for gap analyses: the preconditions, the cache, and running the engine."""

import logging
import time
import uuid
from datetime import UTC, datetime

from app.ai.error_codes import processing_error_code
from app.ai.llm.base import LLMClient
from app.ai.matching import judge, rewrites, screener
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
from app.ai.matching.report import build_report, produce_report
from app.ai.matching.report_models import Report, ReportSettings, ScoreSettings
from app.ai.parsing.models import ParsingIssue
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


class ReportNotReadyError(DomainError):
    status_code = 409
    code = "report_not_ready"


class AnalysisFailedError(DomainError):
    status_code = 409
    code = "analysis_failed"


class ReportNotAvailableError(DomainError):
    status_code = 404
    code = "report_not_available"


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


def score_settings(settings: Settings) -> ScoreSettings:
    return ScoreSettings(
        weight_must_have=settings.score_weight_must_have,
        weight_nice_to_have=settings.score_weight_nice_to_have,
        weight_keywords=settings.score_weight_keywords,
        partial_credit=settings.score_partial_credit,
        penalty_critical=settings.score_penalty_critical,
        penalty_warning=settings.score_penalty_warning,
        penalty_info=settings.score_penalty_info,
        pass_threshold=settings.score_pass_threshold,
        borderline_threshold=settings.score_borderline_threshold,
    )


def report_settings(settings: Settings) -> ReportSettings:
    return ReportSettings(
        screener_runs=settings.screener_runs, max_suggestions=settings.report_max_suggestions
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
        self._score_settings = score_settings(settings)
        self._report_settings = report_settings(settings)

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
        screener_prompt = load_prompt(screener.PROMPT_NAME)
        suggestions_prompt = load_prompt(rewrites.PROMPT_NAME)
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
            screener_prompt=f"{screener_prompt.name}:{screener_prompt.version}",
            suggestions_prompt=f"{suggestions_prompt.name}:{suggestions_prompt.version}",
            report_settings=self._report_settings,
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
            loaded = await self._load(analysis.resume_id, analysis.job_id)
            if loaded is None:
                logger.warning("analysis inputs vanished", extra={"analysis_id": str(analysis_id)})
                return
            inputs, issues = loaded
            result = await analyze(inputs, llm, self._settings, datetime.now(UTC))
            report = await produce_report(
                inputs, result, issues, llm, self._report_settings, datetime.now(UTC)
            )
            if not await self._analyses.save_result(analysis_id, result, report):
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
        _log_finished(analysis_id, result, report.provenance.llm_calls, started)

    async def get_report(self, analysis_id: uuid.UUID) -> Report:
        """The screening report of a `ready` analysis. Computed from the stored result and
        report and the current `SCORE_*` settings; it calls no provider."""
        analysis = await self._analyses.get(analysis_id)
        if analysis is None:
            raise AnalysisNotFoundError("Analysis not found")
        if analysis.status == "processing":
            raise ReportNotReadyError("The analysis is still running: try again in a moment")
        if analysis.status == "failed" or analysis.result is None:
            raise AnalysisFailedError(
                "The analysis failed, so there is no report: read the analysis for the error"
            )
        stored = await self._analyses.get_report(analysis_id)
        if stored is None:
            raise ReportNotAvailableError(
                "This analysis has no report (it was made before reports existed): request the "
                "analysis again"
            )
        return build_report(
            analysis_id=analysis.id,
            resume_id=analysis.resume_id,
            job_id=analysis.job_id,
            result=analysis.result,
            stored=stored,
            score_settings=self._score_settings,
        )

    async def _load(
        self, resume_id: uuid.UUID, job_id: uuid.UUID
    ) -> tuple[AnalysisInput, list[ParsingIssue]] | None:
        """One snapshot of everything the analysis reads (and the resume's parsing issues). None
        when a row is gone."""
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
        inputs = AnalysisInput(
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
        return inputs, list(resume.issues)


def _log_finished(
    analysis_id: uuid.UUID, result: AnalysisResult, report_calls: int, started: float
) -> None:
    logger.info(
        "analysis finished",
        extra={
            "analysis_id": str(analysis_id),
            "requirement_count": len(result.findings),
            "llm_calls": result.provenance.llm_calls,
            "report_llm_calls": report_calls,
            "duration_ms": round((time.perf_counter() - started) * 1000),
        },
    )
