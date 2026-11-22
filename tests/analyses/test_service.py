import dataclasses
import logging
import uuid

import pytest

from app.ai.embeddings.fake import FakeEmbeddingClient
from app.ai.llm.base import LLMAuthError, LLMInvalidOutputError, LLMTimeoutError, LLMTransientError
from app.ai.llm.fake import FakeLLMClient
from app.ai.matching.report_models import ScreenerAnswer, SuggestionBatch
from app.ai.prompts.loader import load_prompt
from app.analyses import service as service_module
from app.analyses.service import (
    AnalysisNotFoundError,
    EmbeddingModelsDifferError,
    JobNotReadyError,
    ProfileRequiredError,
    ResumeNotReadyError,
)
from app.core.processing import PROCESSING_MESSAGES
from app.jobs.service import JobNotFoundError
from app.resumes.service import ResumeNotFoundError
from tests.analyses.env import BULLET, PROFILE_FACT, Env, a_profile, judge, make_env
from tests.analyses.fakes import AnswerAllLLM, ConstantEmbeddingClient


async def _run_to_ready(env: Env, llm=None):  # type: ignore[no-untyped-def]
    llm = llm or judge()
    analysis, started = await env.service.request(env.resume_id, env.job_id, llm)
    assert started
    await env.service.run(analysis.id, llm)
    return await env.service.get(analysis.id), llm


async def test_a_request_stores_a_processing_analysis_and_the_run_makes_it_ready() -> None:
    env = await make_env()
    llm = judge()

    analysis, started = await env.service.request(env.resume_id, env.job_id, llm)

    assert started and analysis.status == "processing" and analysis.result is None
    assert (analysis.resume_id, analysis.job_id) == (env.resume_id, env.job_id)
    await env.service.run(analysis.id, llm)
    ready = await env.service.get(analysis.id)
    assert ready.status == "ready" and ready.error is None and ready.completed_at is not None
    assert ready.result is not None
    job = await env.jobs.get(env.job_id)
    assert job is not None and job.extraction is not None
    assert len(ready.result.findings) == len(job.extraction.job.requirements) > 0
    assert llm.calls >= 1


async def test_an_unknown_resume_or_job_is_a_404_and_nothing_is_stored() -> None:
    env = await make_env()

    with pytest.raises(ResumeNotFoundError):
        await env.service.request(uuid.uuid4(), env.job_id, judge())
    with pytest.raises(JobNotFoundError):
        await env.service.request(env.resume_id, uuid.uuid4(), judge())

    assert env.analyses.by_id == {}


async def test_an_unknown_analysis_is_a_404() -> None:
    env = await make_env()

    with pytest.raises(AnalysisNotFoundError):
        await env.service.get(uuid.uuid4())


@pytest.mark.parametrize("status", ["uploaded", "processing", "failed"])
async def test_a_resume_that_is_not_ready_is_refused(status: str) -> None:
    env = await make_env()
    resume = await env.resumes.get(env.resume_id)
    assert resume is not None
    env.resumes.by_id[env.resume_id] = resume.model_copy(update={"status": status})

    with pytest.raises(ResumeNotReadyError):
        await env.service.request(env.resume_id, env.job_id, judge())

    assert env.analyses.by_id == {}


@pytest.mark.parametrize("status", ["uploaded", "processing", "failed"])
async def test_a_job_that_is_not_ready_is_refused(status: str) -> None:
    env = await make_env()
    job = await env.jobs.get(env.job_id)
    assert job is not None
    env.jobs.by_id[env.job_id] = job.model_copy(update={"status": status})

    with pytest.raises(JobNotReadyError):
        await env.service.request(env.resume_id, env.job_id, judge())

    assert env.analyses.by_id == {}


async def test_no_profile_is_refused_with_a_message_that_says_what_to_do() -> None:
    env = await make_env()
    env.profiles.profile = None

    with pytest.raises(ProfileRequiredError, match=r"PUT /profile"):
        await env.service.request(env.resume_id, env.job_id, judge())

    assert env.analyses.by_id == {}


async def test_different_embedding_models_are_refused() -> None:
    env = await make_env()
    await env.process_job(ConstantEmbeddingClient(model_name="other-model"))

    with pytest.raises(EmbeddingModelsDifferError, match="older"):
        await env.service.request(env.resume_id, env.job_id, judge())

    assert env.analyses.by_id == {}


async def test_the_first_failing_check_is_the_one_reported() -> None:
    env = await make_env()
    for repo, ident in ((env.resumes, env.resume_id), (env.jobs, env.job_id)):
        entry = repo.by_id[ident]
        repo.by_id[ident] = entry.model_copy(update={"status": "uploaded"})
    env.profiles.profile = None

    with pytest.raises(ResumeNotReadyError):
        await env.service.request(env.resume_id, env.job_id, judge())

    resume = env.resumes.by_id[env.resume_id]
    env.resumes.by_id[env.resume_id] = resume.model_copy(update={"status": "ready"})
    with pytest.raises(JobNotReadyError):
        await env.service.request(env.resume_id, env.job_id, judge())

    job = env.jobs.by_id[env.job_id]
    env.jobs.by_id[env.job_id] = job.model_copy(update={"status": "ready"})
    with pytest.raises(ProfileRequiredError):
        await env.service.request(env.resume_id, env.job_id, judge())


# --- the cache --------------------------------------------------------------------------------


async def test_the_same_request_again_returns_the_ready_analysis_without_the_llm() -> None:
    env = await make_env()
    first, llm = await _run_to_ready(env)
    calls = llm.calls

    again, started = await env.service.request(env.resume_id, env.job_id, llm)

    assert not started and again.id == first.id and again.status == "ready"
    assert llm.calls == calls
    assert len(env.analyses.by_id) == 1


async def test_the_same_request_while_running_returns_the_running_analysis() -> None:
    env = await make_env()
    llm = judge()
    first, _ = await env.service.request(env.resume_id, env.job_id, llm)

    again, started = await env.service.request(env.resume_id, env.job_id, llm)

    assert not started and again.id == first.id and again.status == "processing"


async def test_a_failed_analysis_is_followed_by_a_new_one() -> None:
    env = await make_env()
    failing = FakeLLMClient([LLMTimeoutError("x")], provider="fake", model="fake-model")
    first, _ = await env.service.request(env.resume_id, env.job_id, failing)
    await env.service.run(first.id, failing)
    assert (await env.service.get(first.id)).status == "failed"

    second, started = await env.service.request(env.resume_id, env.job_id, failing)

    assert started and second.id != first.id and len(env.analyses.by_id) == 2


async def test_a_changed_profile_starts_a_new_analysis_and_keeps_the_old_one() -> None:
    env = await make_env()
    first, llm = await _run_to_ready(env)
    env.profiles.profile = a_profile(notable_facts=["Something new"])

    second, started = await env.service.request(env.resume_id, env.job_id, llm)

    assert started and second.id != first.id
    assert (await env.service.get(first.id)).status == "ready"


async def test_a_resume_processed_again_starts_a_new_analysis() -> None:
    env = await make_env()
    first, llm = await _run_to_ready(env)
    await env.process_resume()

    second, started = await env.service.request(env.resume_id, env.job_id, llm)

    assert started and second.id != first.id


async def test_a_job_processed_again_starts_a_new_analysis() -> None:
    env = await make_env()
    first, llm = await _run_to_ready(env)
    await env.process_job()

    second, started = await env.service.request(env.resume_id, env.job_id, llm)

    assert started and second.id != first.id


async def test_a_new_prompt_version_starts_a_new_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    env = await make_env()
    first, llm = await _run_to_ready(env)
    newer = dataclasses.replace(load_prompt("gap_judge"), version=2)
    monkeypatch.setattr(service_module, "load_prompt", lambda _name: newer)

    second, started = await env.service.request(env.resume_id, env.job_id, llm)

    assert started and second.id != first.id


async def test_another_llm_model_starts_a_new_analysis() -> None:
    env = await make_env()
    first, llm = await _run_to_ready(env)

    from tests.analyses.fakes import AnswerAllLLM

    second, started = await env.service.request(
        env.resume_id, env.job_id, AnswerAllLLM(model="other-model")
    )

    assert started and second.id != first.id and llm.calls >= 1


async def test_other_analysis_settings_start_a_new_analysis() -> None:
    env = await make_env()
    first, llm = await _run_to_ready(env)
    other = await make_env(analysis_top_k=3)
    other.analyses = env.analyses
    other.service = type(env.service)(
        env.analyses,  # type: ignore[arg-type]
        env.resumes,  # type: ignore[arg-type]
        env.jobs,  # type: ignore[arg-type]
        env.profiles,  # type: ignore[arg-type]
        other.settings,
    )

    second, started = await other.service.request(env.resume_id, env.job_id, llm)

    assert started and second.id != first.id


# --- failures ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (LLMAuthError("x"), "llm_auth_failed"),
        (LLMTimeoutError("x"), "llm_timeout"),
        (LLMTransientError("x"), "llm_unavailable"),
        (LLMInvalidOutputError("x"), "llm_invalid_output"),
        (RuntimeError("secret text: " + BULLET), "processing_failed"),
    ],
)
async def test_every_failure_ends_as_failed_with_a_fixed_message(
    error: Exception, code: str
) -> None:
    env = await make_env()
    llm = FakeLLMClient([error])
    analysis, _ = await env.service.request(env.resume_id, env.job_id, llm)

    await env.service.run(analysis.id, llm)

    failed = await env.service.get(analysis.id)
    assert failed.status == "failed" and failed.result is None and failed.error is not None
    assert failed.error.code == code
    assert failed.error.message == PROCESSING_MESSAGES[code]
    assert BULLET not in failed.error.message


async def test_too_many_requirements_to_judge_fail_before_any_call() -> None:
    env = await make_env(analysis_max_requirements_per_call=1, analysis_max_llm_calls=1)
    llm = judge()
    analysis, _ = await env.service.request(env.resume_id, env.job_id, llm)

    await env.service.run(analysis.id, llm)

    failed = await env.service.get(analysis.id)
    assert failed.error is not None and failed.error.code == "analysis_limit_exceeded"
    assert llm.calls == 0


async def test_vectors_from_different_models_found_at_run_time_fail_the_analysis() -> None:
    env = await make_env()
    llm = judge()
    analysis, _ = await env.service.request(env.resume_id, env.job_id, llm)
    await env.process_job(ConstantEmbeddingClient(model_name="other-model"))

    await env.service.run(analysis.id, llm)

    failed = await env.service.get(analysis.id)
    assert failed.error is not None and failed.error.code == "embedding_model_mismatch"


async def test_a_resume_that_is_no_longer_ready_fails_the_analysis_safely() -> None:
    env = await make_env()
    llm = judge()
    analysis, _ = await env.service.request(env.resume_id, env.job_id, llm)
    resume = env.resumes.by_id[env.resume_id]
    env.resumes.by_id[env.resume_id] = resume.model_copy(update={"status": "processing"})

    await env.service.run(analysis.id, llm)

    failed = await env.service.get(analysis.id)
    assert failed.error is not None and failed.error.code == "processing_failed"


async def test_running_a_deleted_analysis_is_a_no_op() -> None:
    env = await make_env()

    await env.service.run(uuid.uuid4(), judge())

    assert env.analyses.by_id == {}


async def test_a_resume_deleted_while_running_leaves_nothing_behind() -> None:
    env = await make_env()
    llm = judge()
    analysis, _ = await env.service.request(env.resume_id, env.job_id, llm)
    await env.resumes.delete(env.resume_id)
    env.analyses.by_id.pop(analysis.id)  # the database cascade

    await env.service.run(analysis.id, llm)

    assert env.analyses.by_id == {}


async def test_the_provenance_counts_the_llm_calls_that_were_made() -> None:
    env = await make_env(FakeEmbeddingClient(1024, "fake"))  # vectors that resemble nothing
    llm = judge()
    analysis, _ = await env.service.request(env.resume_id, env.job_id, llm)

    await env.service.run(analysis.id, llm)

    ready = await env.service.get(analysis.id)
    assert ready.status == "ready" and ready.result is not None
    assert ready.result.provenance.llm_calls == llm.judge_calls


# --- privacy ----------------------------------------------------------------------------------


async def test_no_log_record_contains_resume_job_or_profile_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = await make_env()
    llm = judge()

    with caplog.at_level(logging.DEBUG):
        analysis, _ = await env.service.request(env.resume_id, env.job_id, llm)
        await env.service.run(analysis.id, llm)
        failing = FakeLLMClient([RuntimeError(BULLET)])
        second, _ = await env.service.request(env.resume_id, env.job_id, failing)  # cache hit
        env.profiles.profile = a_profile(notable_facts=["Another secret fact"])
        third, _ = await env.service.request(env.resume_id, env.job_id, failing)
        await env.service.run(third.id, failing)

    assert second.id == analysis.id
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for secret in (BULLET, PROFILE_FACT, "Another secret fact", "Senior Backend Engineer"):
        assert secret not in text


def test_every_score_setting_reaches_the_snapshot() -> None:
    from app.core.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost/x",
        score_weight_must_have=0.5,
        score_weight_nice_to_have=0.2,
        score_weight_keywords=0.3,
        score_partial_credit=0.4,
        score_penalty_critical=30,
        score_penalty_warning=6,
        score_penalty_info=2,
        score_pass_threshold=80,
        score_borderline_threshold=45,
    )

    snapshot = service_module.score_settings(settings)

    assert snapshot.model_dump() == {
        "weight_must_have": 0.5,
        "weight_nice_to_have": 0.2,
        "weight_keywords": 0.3,
        "partial_credit": 0.4,
        "penalty_critical": 30,
        "penalty_warning": 6,
        "penalty_info": 2,
        "pass_threshold": 80,
        "borderline_threshold": 45,
    }


# --- the report -------------------------------------------------------------------------------


class _ScreenerDown(AnswerAllLLM):
    async def generate_structured(self, prompt, schema, *, system=None):  # type: ignore[no-untyped-def]
        if schema is ScreenerAnswer:
            raise LLMTransientError("down")
        return await super().generate_structured(prompt, schema, system=system)


def _another_service(env: Env, **overrides: object) -> service_module.AnalysisService:
    settings = env.settings.model_copy(update=overrides)
    return service_module.AnalysisService(
        env.analyses,  # type: ignore[arg-type]
        env.resumes,  # type: ignore[arg-type]
        env.jobs,  # type: ignore[arg-type]
        env.profiles,  # type: ignore[arg-type]
        settings,
    )


async def test_a_successful_run_stores_the_result_and_the_report_together() -> None:
    env = await make_env()

    ready, llm = await _run_to_ready(env)

    assert ready.result is not None
    stored = env.analyses.reports[ready.id]
    assert len(stored.screener.runs) == 3 == llm.schemas.count(ScreenerAnswer)
    assert stored.language == "en"
    assert stored.provenance.llm_provider == "fake"
    assert [i.code for i in stored.issues] == [
        i.code
        for i in (await env.resumes.get(env.resume_id)).issues  # type: ignore[union-attr]
    ]


async def test_a_screener_failure_fails_the_analysis_and_stores_nothing() -> None:
    env = await make_env()
    llm = _ScreenerDown()
    analysis, _ = await env.service.request(env.resume_id, env.job_id, llm)

    await env.service.run(analysis.id, llm)

    failed = await env.service.get(analysis.id)
    assert failed.status == "failed" and failed.result is None
    assert failed.error is not None and failed.error.code == "llm_unavailable"
    assert analysis.id not in env.analyses.reports
    with pytest.raises(service_module.AnalysisFailedError):
        await env.service.get_report(analysis.id)
    # a new request starts a new run
    again, started = await env.service.request(env.resume_id, env.job_id, judge())
    assert started and again.id != analysis.id


async def test_the_report_calls_are_counted_apart_from_the_judge_limit() -> None:
    env = await make_env(analysis_max_requirements_per_call=50, analysis_max_llm_calls=1)

    ready, llm = await _run_to_ready(env)

    stored = env.analyses.reports[ready.id]
    assert ready.status == "ready"
    assert llm.judge_calls == 1
    assert stored.provenance.llm_calls == llm.schemas.count(ScreenerAnswer) + llm.schemas.count(
        SuggestionBatch
    )
    assert stored.provenance.llm_calls > env.settings.analysis_max_llm_calls
    assert ready.result is not None and ready.result.provenance.llm_calls == 1


async def test_the_report_can_be_read_and_follows_the_settings_in_force() -> None:
    env = await make_env()
    ready, llm = await _run_to_ready(env)
    calls = llm.calls

    strict = await env.service.get_report(ready.id)
    lenient = await _another_service(
        env, score_pass_threshold=1, score_borderline_threshold=0.5
    ).get_report(ready.id)

    assert strict.analysis_id == ready.id and strict.disclaimer
    assert strict.score.value == lenient.score.value
    assert lenient.score.outcome == "likely_pass" and strict.score.outcome != "likely_pass"
    assert strict.screener.runs == lenient.screener.runs
    assert llm.calls == calls  # reading a report spends nothing


async def test_the_errors_of_reading_a_report() -> None:
    env = await make_env()
    with pytest.raises(AnalysisNotFoundError):
        await env.service.get_report(uuid.uuid4())

    processing, _ = await env.service.request(env.resume_id, env.job_id, judge())
    with pytest.raises(service_module.ReportNotReadyError):
        await env.service.get_report(processing.id)

    await env.service.run(processing.id, judge())
    env.analyses.reports.pop(processing.id)
    with pytest.raises(service_module.ReportNotAvailableError):
        await env.service.get_report(processing.id)


async def test_no_log_record_of_a_run_or_a_read_contains_report_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = await make_env()

    with caplog.at_level(logging.DEBUG):
        ready, _ = await _run_to_ready(env)
        report = await env.service.get_report(ready.id)

    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert report.screener.runs[0].reasons[0] == "Mixed."
    assert "Mixed." not in logged and BULLET not in logged
    for finding in ready.result.findings if ready.result else []:
        assert finding.requirement_text not in logged
    for action in report.actions:
        assert action.text not in logged


# --- the cache and the report -----------------------------------------------------------------


async def test_other_screener_runs_start_a_new_analysis() -> None:
    env = await make_env()
    first, llm = await _run_to_ready(env)

    second, started = await _another_service(env, screener_runs=5).request(
        env.resume_id, env.job_id, llm
    )

    assert started and second.id != first.id


async def test_another_suggestions_cap_starts_a_new_analysis() -> None:
    env = await make_env()
    first, llm = await _run_to_ready(env)

    second, started = await _another_service(env, report_max_suggestions=0).request(
        env.resume_id, env.job_id, llm
    )

    assert started and second.id != first.id


async def test_a_score_setting_does_not_start_a_new_analysis() -> None:
    env = await make_env()
    first, llm = await _run_to_ready(env)
    calls = llm.calls

    again, started = await _another_service(env, score_pass_threshold=90).request(
        env.resume_id, env.job_id, llm
    )

    assert not started and again.id == first.id and llm.calls == calls


async def test_an_analysis_without_a_report_is_never_returned_by_a_new_request() -> None:
    env = await make_env()
    old, llm = await _run_to_ready(env)
    # what an analysis made before reports looks like: its key was made without the report parts
    env.analyses.keys[old.id] = "key-from-before-reports"
    env.analyses.reports.pop(old.id)

    again, started = await env.service.request(env.resume_id, env.job_id, llm)

    assert started and again.id != old.id
