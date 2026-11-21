import logging
import uuid

import pytest

from app.ai.embeddings.base import EmbeddingTransientError
from app.ai.embeddings.fake import FakeEmbeddingClient
from app.ai.llm.base import (
    LLMAuthError,
    LLMError,
    LLMInvalidOutputError,
    LLMTimeoutError,
    LLMTransientError,
)
from app.ai.llm.fake import FakeLLMClient
from app.core.processing import PROCESSING_MESSAGES, AlreadyProcessingError
from app.jobs.schemas import JobIn
from app.jobs.service import JobNotFoundError, JobService
from tests.fixtures.job_postings import ENGLISH, UNCLEAR
from tests.jobs.fakes import FakeJobRepository
from tests.jobs.support import job_from, stored_job


def _service() -> tuple[JobService, FakeJobRepository]:
    repository = FakeJobRepository()
    return JobService(repository), repository  # type: ignore[arg-type]


async def test_create_stores_a_new_uploaded_job() -> None:
    service, repository = _service()

    job = await service.create(
        JobIn(title="Backend", company="ACME", description="d", requirements_text="r")
    )

    assert (job.status, job.error, job.extraction) == ("uploaded", None, None)
    assert repository.by_id[job.id] == job
    assert (await service.get(job.id)) == job


async def test_two_identical_creates_make_two_jobs() -> None:
    service, _ = _service()
    data = JobIn(title="Backend", description="d")

    first, second = await service.create(data), await service.create(data)

    assert first.id != second.id
    assert len(await service.list_all()) == 2


async def test_get_and_delete_of_an_unknown_job_are_not_found() -> None:
    service, _ = _service()

    with pytest.raises(JobNotFoundError) as exc_info:
        await service.get(uuid.uuid4())
    with pytest.raises(JobNotFoundError):
        await service.delete(uuid.uuid4())
    assert (exc_info.value.status_code, exc_info.value.code) == (404, "job_not_found")


async def test_delete_removes_the_job() -> None:
    service, repository = _service()
    job = await service.create(JobIn(title="t", description="d"))

    await service.delete(job.id)

    assert job.id not in repository.by_id
    with pytest.raises(JobNotFoundError):
        await service.delete(job.id)


async def test_start_marks_processing_and_rejects_unknown_and_running_jobs() -> None:
    service, repository = _service()
    job = stored_job()
    repository.by_id[job.id] = job

    assert (await service.start_processing(job.id)).status == "processing"
    with pytest.raises(AlreadyProcessingError):
        await service.start_processing(job.id)
    with pytest.raises(JobNotFoundError):
        await service.start_processing(uuid.uuid4())


@pytest.mark.parametrize("status", ["ready", "failed", "uploaded"])
async def test_a_job_that_is_not_processing_can_be_started(status: str) -> None:
    service, repository = _service()
    job = stored_job(status=status)
    repository.by_id[job.id] = job

    assert (await service.start_processing(job.id)).status == "processing"


async def _started(posting_job):  # type: ignore[no-untyped-def]
    service, repository = _service()
    repository.by_id[posting_job.id] = posting_job
    await service.start_processing(posting_job.id)
    return service, repository


async def test_success_stores_the_extraction_and_the_requirements() -> None:
    job = job_from(ENGLISH)
    service, repository = await _started(job)

    await service.run_processing(
        job.id, FakeLLMClient(list(ENGLISH.answers)), FakeEmbeddingClient(8, "fake-bge")
    )

    stored = repository.by_id[job.id]
    assert (stored.status, stored.error) == ("ready", None)
    assert stored.extraction is not None
    assert len(stored.extraction.job.requirements) == len(ENGLISH.requirements)
    processed = repository.requirements[job.id]
    assert processed.embedding_model == "fake-bge"
    assert len(processed.requirements) == len(ENGLISH.requirements)


async def test_the_posting_text_is_the_description_followed_by_the_requirements_text() -> None:
    job = stored_job("About the role.").model_copy(update={"requirements_text": "- Python"})
    service, _ = await _started(job)
    llm = FakeLLMClient([UNCLEAR.answers[0].model_copy(update={"requirements": []})])

    await service.run_processing(job.id, llm, FakeEmbeddingClient(8))

    assert "About the role.\n\n- Python" in llm.calls[0].prompt


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (LLMAuthError("status 401"), "llm_auth_failed"),
        (LLMTimeoutError("slow"), "llm_timeout"),
        (LLMTransientError("status 503"), "llm_unavailable"),
        (LLMInvalidOutputError("bad json"), "llm_invalid_output"),
        (LLMError("other rejection"), "processing_failed"),
        (RuntimeError("boom"), "processing_failed"),
    ],
)
async def test_every_failure_ends_failed_with_its_code_and_a_fixed_message(
    error: Exception, code: str
) -> None:
    job = job_from(ENGLISH)
    service, repository = await _started(job)

    await service.run_processing(job.id, FakeLLMClient([error]), FakeEmbeddingClient(8))

    stored = repository.by_id[job.id]
    assert stored.status == "failed" and stored.error is not None
    assert (stored.error.code, stored.error.message) == (code, PROCESSING_MESSAGES[code])


async def test_an_embedding_failure_is_reported_as_embedding_failed() -> None:
    class Failing(FakeEmbeddingClient):
        async def embed(self, texts):  # type: ignore[no-untyped-def]
            raise EmbeddingTransientError("status 503")

    job = job_from(ENGLISH)
    service, repository = await _started(job)

    await service.run_processing(job.id, FakeLLMClient(list(ENGLISH.answers)), Failing(8))

    assert repository.by_id[job.id].error.code == "embedding_failed"  # type: ignore[union-attr]
    assert job.id not in repository.requirements


async def test_an_unexpected_error_text_never_reaches_the_stored_error() -> None:
    job = job_from(ENGLISH)
    service, repository = await _started(job)
    secret = RuntimeError("leaked Strong knowledge of Python and sk-secret")

    await service.run_processing(job.id, FakeLLMClient([secret]), FakeEmbeddingClient(8))

    error = repository.by_id[job.id].error
    assert error is not None
    assert "sk-secret" not in error.message and "Python" not in error.message


async def test_a_failed_reprocess_keeps_the_previous_results() -> None:
    job = job_from(ENGLISH)
    service, repository = await _started(job)
    await service.run_processing(
        job.id, FakeLLMClient(list(ENGLISH.answers)), FakeEmbeddingClient(8)
    )
    first = repository.by_id[job.id].extraction

    await service.start_processing(job.id)
    await service.run_processing(
        job.id, FakeLLMClient([LLMTimeoutError("x")]), FakeEmbeddingClient(8)
    )

    stored = repository.by_id[job.id]
    assert stored.status == "failed" and stored.extraction == first
    assert job.id in repository.requirements


async def test_a_job_deleted_while_processing_is_not_an_error() -> None:
    job = job_from(ENGLISH)
    service, repository = await _started(job)
    llm = FakeLLMClient(list(ENGLISH.answers))
    original = llm.generate_structured

    async def generate(*args, **kwargs):  # type: ignore[no-untyped-def]
        repository.by_id.pop(job.id, None)
        return await original(*args, **kwargs)

    llm.generate_structured = generate  # type: ignore[method-assign]

    await service.run_processing(job.id, llm, FakeEmbeddingClient(8))

    assert job.id not in repository.by_id


async def test_a_job_that_vanished_before_the_work_started_is_ignored() -> None:
    service, _ = _service()

    await service.run_processing(uuid.uuid4(), FakeLLMClient(), FakeEmbeddingClient(8))


async def test_logs_have_ids_counts_and_codes_but_no_posting_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, repository = _service()
    ok, bad = job_from(ENGLISH), job_from(ENGLISH)
    repository.by_id |= {ok.id: ok, bad.id: bad}
    with caplog.at_level(logging.DEBUG):
        created = await service.create(
            JobIn(title="Secret Title", company="Secret Co", description="d")
        )
        await service.start_processing(ok.id)
        await service.run_processing(
            ok.id, FakeLLMClient(list(ENGLISH.answers)), FakeEmbeddingClient(8)
        )
        await service.start_processing(bad.id)
        await service.run_processing(
            bad.id, FakeLLMClient([RuntimeError(ENGLISH.text)]), FakeEmbeddingClient(8)
        )
        await service.delete(created.id)

    finished = next(r for r in caplog.records if r.getMessage() == "job processing finished")
    assert finished.__dict__["requirement_count"] == len(ENGLISH.requirements)
    failed = next(r for r in caplog.records if r.getMessage() == "job processing failed")
    assert failed.__dict__["error_code"] == "processing_failed"
    logged = " ".join(str(r.__dict__) + r.getMessage() for r in caplog.records)
    for fragment in (
        "Secret Title",
        "Secret Co",
        "Java",
        "Terraform",
        "Backend Engineer",
        "payments",
    ):
        assert fragment not in logged


async def test_the_same_failure_gives_the_same_code_and_message_for_jobs_and_resumes() -> None:
    from app.resumes.service import ResumeService
    from tests.resumes.fakes import FakeRepository, FakeStorage
    from tests.resumes.processing import stored_resume

    job = job_from(ENGLISH)
    job_service, job_repository = await _started(job)
    await job_service.run_processing(
        job.id, FakeLLMClient([LLMTimeoutError("x")]), FakeEmbeddingClient(8)
    )

    resume_repository = FakeRepository()
    resume = stored_resume()
    resume_repository.by_id[resume.id] = resume
    resume_service = ResumeService(resume_repository, FakeStorage(), 1)  # type: ignore[arg-type]
    await resume_service.start_processing(resume.id)
    await resume_service.run_processing(
        resume.id, FakeLLMClient([LLMTimeoutError("x")]), FakeEmbeddingClient(8)
    )

    assert job_repository.by_id[job.id].error == resume_repository.by_id[resume.id].error
