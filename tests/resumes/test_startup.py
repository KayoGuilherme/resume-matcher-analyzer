import logging

import pytest

from app.ai.embeddings.dimension import (
    EmbeddingDimensionMismatchError,
    check_embedding_dimension,
)
from app.core.config import Settings
from app.core.processing import PROCESSING_MESSAGES
from app.resumes.startup import run_startup, run_startup_checks
from tests.resumes.fakes import FakeRepository
from tests.resumes.processing import stored_resume

DB = "postgresql+asyncpg://u:p@localhost:5432/x"


def _settings(**values: object) -> Settings:
    return Settings(database_url=DB, **values)  # type: ignore[arg-type]


def test_matching_dimensions_pass() -> None:
    check_embedding_dimension(1024, 1024)


def test_a_missing_table_passes() -> None:
    check_embedding_dimension(1024, None)


def test_a_mismatch_states_both_sizes_and_points_to_the_procedure() -> None:
    with pytest.raises(EmbeddingDimensionMismatchError) as exc_info:
        check_embedding_dimension(768, 1024)

    message = str(exc_info.value)
    assert "768" in message and "1024" in message
    assert "Changing the embedding model" in message
    assert "EMBEDDING_DIMENSION" in message


async def test_the_checks_fail_on_a_mismatch_and_recover_nothing() -> None:
    repository = FakeRepository()
    repository.column_dimension = 1024
    resume = stored_resume(status="processing")
    repository.by_id[resume.id] = resume

    with pytest.raises(EmbeddingDimensionMismatchError):
        await run_startup_checks(repository, _settings(embedding_dimension=768))

    assert repository.by_id[resume.id].status == "processing"


async def test_the_checks_pass_and_recover_interrupted_processing() -> None:
    repository = FakeRepository()
    stuck = stored_resume(status="processing")
    fine = stored_resume(status="ready")
    repository.by_id |= {stuck.id: stuck, fine.id: fine}

    await run_startup_checks(repository, _settings())

    recovered = repository.by_id[stuck.id]
    assert recovered.status == "failed"
    assert recovered.error is not None
    assert recovered.error.code == "processing_interrupted"
    assert repository.by_id[fine.id].status == "ready"
    assert repository.interrupted_message == PROCESSING_MESSAGES["processing_interrupted"]


async def test_without_the_chunk_table_the_checks_are_skipped_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeRepository()
    repository.column_dimension = None
    stuck = stored_resume(status="processing")
    repository.by_id[stuck.id] = stuck

    with caplog.at_level(logging.WARNING):
        await run_startup_checks(repository, _settings(embedding_dimension=1))

    assert "skipped" in caplog.text
    assert repository.by_id[stuck.id].status == "processing"


async def test_an_unreachable_database_only_skips_the_checks(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(_settings: Settings) -> object:
        raise ConnectionRefusedError("postgres://u:secret@host/db")

    monkeypatch.setattr("app.resumes.startup.get_sessionmaker", unreachable)

    with caplog.at_level(logging.WARNING):
        await run_startup(_settings())

    assert "not reachable" in caplog.text
    assert "secret" not in caplog.text


async def test_a_dimension_mismatch_is_not_swallowed_by_the_unreachable_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository()

    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("app.resumes.startup.get_sessionmaker", lambda _s: lambda: Session())
    monkeypatch.setattr("app.resumes.startup.ResumeRepository", lambda _session: repository)

    with pytest.raises(EmbeddingDimensionMismatchError):
        await run_startup(_settings(embedding_dimension=768))
