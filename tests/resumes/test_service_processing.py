import logging
import uuid

import pytest

from app.ai.embeddings.base import (
    EmbeddingAuthError,
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingTransientError,
)
from app.ai.embeddings.fake import FakeEmbeddingClient
from app.ai.error_codes import processing_error_code
from app.ai.llm.base import (
    LLMAuthError,
    LLMError,
    LLMInvalidOutputError,
    LLMTimeoutError,
    LLMTransientError,
)
from app.ai.llm.fake import FakeLLMClient
from app.core.processing import PROCESSING_MESSAGES, AlreadyProcessingError
from app.resumes.service import ResumeNotFoundError, ResumeService
from tests.ai.extraction.builders import RESUME_TEXT, experience, extracted
from tests.resumes.fakes import FakeRepository, FakeStorage
from tests.resumes.processing import stored_resume

GOOD = "Reduced p95 latency by 40%"


def _service() -> tuple[ResumeService, FakeRepository]:
    repository = FakeRepository()
    return ResumeService(repository, FakeStorage(), 5 * 1024 * 1024), repository  # type: ignore[arg-type]


def _answer() -> object:
    return extracted(experiences=[experience(GOOD)], skills=["Cloud: AWS, Docker"])


async def _processing(repository: FakeRepository) -> uuid.UUID:
    resume = stored_resume()
    repository.by_id[resume.id] = resume
    return resume.id


async def test_start_marks_the_resume_processing_and_returns_it() -> None:
    service, repository = _service()
    resume_id = await _processing(repository)

    resume = await service.start_processing(resume_id)

    assert resume.status == "processing"
    assert resume.id == resume_id


async def test_start_on_an_unknown_resume_is_not_found() -> None:
    service, _ = _service()

    with pytest.raises(ResumeNotFoundError):
        await service.start_processing(uuid.uuid4())


async def test_start_while_processing_is_a_conflict() -> None:
    service, repository = _service()
    resume_id = await _processing(repository)
    await service.start_processing(resume_id)

    with pytest.raises(AlreadyProcessingError) as exc_info:
        await service.start_processing(resume_id)

    assert (exc_info.value.status_code, exc_info.value.code) == (409, "already_processing")


@pytest.mark.parametrize("status", ["ready", "failed", "uploaded"])
async def test_a_resume_that_is_not_processing_can_be_started(status: str) -> None:
    service, repository = _service()
    resume = stored_resume(status=status)
    repository.by_id[resume.id] = resume

    assert (await service.start_processing(resume.id)).status == "processing"


async def test_success_stores_the_extraction_and_the_chunks() -> None:
    service, repository = _service()
    resume_id = await _processing(repository)
    await service.start_processing(resume_id)

    await service.run_processing(
        resume_id,
        FakeLLMClient([_answer()]),
        FakeEmbeddingClient(dimension=8, model_name="fake-bge"),  # type: ignore[list-item]
    )

    resume = repository.by_id[resume_id]
    assert (resume.status, resume.error) == ("ready", None)
    assert resume.extraction is not None
    assert resume.extraction.total_experience_months == 24
    processed = repository.chunks[resume_id]
    assert processed.embedding_model == "fake-bge"
    assert [c.chunk.text for c in processed.chunks] == ["Cloud: AWS, Docker", GOOD]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (LLMAuthError("status 401"), "llm_auth_failed"),
        (LLMTimeoutError("slow"), "llm_timeout"),
        (LLMTransientError("status 503"), "llm_unavailable"),
        (LLMInvalidOutputError("bad json"), "llm_invalid_output"),
        (EmbeddingTransientError("x"), "embedding_failed"),
        (EmbeddingAuthError("x"), "embedding_failed"),
        (EmbeddingDimensionError(1024, 768), "embedding_failed"),
        (EmbeddingError("x"), "embedding_failed"),
        (LLMError("other rejection"), "processing_failed"),
        (RuntimeError("boom"), "processing_failed"),
    ],
)
async def test_every_failure_ends_as_failed_with_its_code_and_a_fixed_message(
    error: Exception, code: str
) -> None:
    service, repository = _service()
    resume_id = await _processing(repository)
    await service.start_processing(resume_id)

    await service.run_processing(resume_id, FakeLLMClient([error]), FakeEmbeddingClient(8))

    resume = repository.by_id[resume_id]
    assert resume.status == "failed"
    assert resume.error is not None
    assert (resume.error.code, resume.error.message) == (code, PROCESSING_MESSAGES[code])
    assert processing_error_code(error) == code


async def test_a_failure_while_embedding_is_reported_as_an_embedding_failure() -> None:
    class Failing(FakeEmbeddingClient):
        async def embed(self, texts):  # type: ignore[no-untyped-def]
            raise EmbeddingTransientError("status 503")

    service, repository = _service()
    resume_id = await _processing(repository)
    await service.start_processing(resume_id)

    await service.run_processing(resume_id, FakeLLMClient([_answer()]), Failing(8))  # type: ignore[list-item]

    assert repository.by_id[resume_id].error.code == "embedding_failed"  # type: ignore[union-attr]
    assert resume_id not in repository.chunks


async def test_messages_contain_no_exception_text_or_resume_text() -> None:
    service, repository = _service()
    resume_id = await _processing(repository)
    await service.start_processing(resume_id)
    secret = RuntimeError(f"leaked {RESUME_TEXT[:30]} sk-secret-key")

    await service.run_processing(resume_id, FakeLLMClient([secret]), FakeEmbeddingClient(8))

    error = repository.by_id[resume_id].error
    assert error is not None
    assert "sk-secret-key" not in error.message
    assert RESUME_TEXT[:30] not in error.message


async def test_a_failed_reprocess_keeps_the_previous_results() -> None:
    service, repository = _service()
    resume_id = await _processing(repository)
    await service.start_processing(resume_id)
    await service.run_processing(resume_id, FakeLLMClient([_answer()]), FakeEmbeddingClient(8))  # type: ignore[list-item]
    first = repository.by_id[resume_id].extraction

    await service.start_processing(resume_id)
    await service.run_processing(
        resume_id, FakeLLMClient([LLMTimeoutError("x")]), FakeEmbeddingClient(8)
    )

    resume = repository.by_id[resume_id]
    assert resume.status == "failed"
    assert resume.extraction == first
    assert resume_id in repository.chunks


async def test_a_resume_deleted_while_processing_is_not_an_error() -> None:
    service, repository = _service()
    resume_id = await _processing(repository)
    await service.start_processing(resume_id)
    llm = FakeLLMClient([_answer()])

    async def delete_during_llm_call(*args: object, **kwargs: object) -> None:
        repository.by_id.pop(resume_id)

    original = llm.generate_structured

    async def generate(*args, **kwargs):  # type: ignore[no-untyped-def]
        await delete_during_llm_call()
        return await original(*args, **kwargs)

    llm.generate_structured = generate  # type: ignore[method-assign]

    await service.run_processing(resume_id, llm, FakeEmbeddingClient(8))

    assert resume_id not in repository.by_id


async def test_a_resume_that_vanished_before_the_work_started_is_ignored() -> None:
    service, _ = _service()

    await service.run_processing(uuid.uuid4(), FakeLLMClient(), FakeEmbeddingClient(8))


async def test_logs_have_ids_counts_and_codes_but_no_resume_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, repository = _service()
    ok = await _processing(repository)
    bad = await _processing(repository)
    with caplog.at_level(logging.DEBUG):
        await service.start_processing(ok)
        await service.run_processing(ok, FakeLLMClient([_answer()]), FakeEmbeddingClient(8))  # type: ignore[list-item]
        await service.start_processing(bad)
        await service.run_processing(
            bad, FakeLLMClient([RuntimeError(RESUME_TEXT)]), FakeEmbeddingClient(8)
        )

    messages = [r.getMessage() for r in caplog.records]
    assert "resume processing started" in messages
    assert "resume processing finished" in messages
    assert "resume processing failed" in messages
    finished = next(r for r in caplog.records if r.getMessage() == "resume processing finished")
    assert finished.__dict__["chunk_count"] == 2
    failed = next(r for r in caplog.records if r.getMessage() == "resume processing failed")
    assert failed.__dict__["error_code"] == "processing_failed"
    assert failed.__dict__["exception_type"] == "RuntimeError"
    logged = " ".join(str(r.__dict__) + r.getMessage() for r in caplog.records)
    for fragment in ("p95", "Spring Boot", "Desenvolvedora", "Backend Developer"):
        assert fragment not in logged
