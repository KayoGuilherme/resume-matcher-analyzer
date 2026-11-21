import logging

import pytest

from app.ai.embeddings.dimension import EmbeddingDimensionMismatchError
from app.core.config import Settings
from app.core.processing import PROCESSING_MESSAGES
from app.jobs.startup import run_job_startup_checks, run_jobs_startup
from tests.jobs.fakes import FakeJobRepository
from tests.jobs.support import stored_job

DB = "postgresql+asyncpg://u:p@localhost:5432/x"


def _settings(**values: object) -> Settings:
    return Settings(database_url=DB, **values)  # type: ignore[arg-type]


async def test_a_mismatch_names_the_table_both_sizes_and_the_procedure() -> None:
    repository = FakeJobRepository()
    repository.column_dimension = 1024

    with pytest.raises(EmbeddingDimensionMismatchError) as exc_info:
        await run_job_startup_checks(repository, _settings(embedding_dimension=768))  # type: ignore[arg-type]

    message = str(exc_info.value)
    assert "job_requirements" in message and "768" in message and "1024" in message
    assert "Changing the embedding model" in message


async def test_a_mismatch_recovers_nothing() -> None:
    repository = FakeJobRepository()
    stuck = stored_job(status="processing")
    repository.by_id[stuck.id] = stuck

    with pytest.raises(EmbeddingDimensionMismatchError):
        await run_job_startup_checks(repository, _settings(embedding_dimension=768))  # type: ignore[arg-type]

    assert repository.by_id[stuck.id].status == "processing"


async def test_matching_dimensions_pass_and_interrupted_jobs_are_recovered() -> None:
    repository = FakeJobRepository()
    stuck, fine = stored_job(status="processing"), stored_job(status="ready")
    repository.by_id |= {stuck.id: stuck, fine.id: fine}

    await run_job_startup_checks(repository, _settings())  # type: ignore[arg-type]

    recovered = repository.by_id[stuck.id]
    assert recovered.status == "failed" and recovered.error is not None
    assert recovered.error.code == "processing_interrupted"
    assert repository.by_id[fine.id].status == "ready"
    assert repository.interrupted_message == PROCESSING_MESSAGES["processing_interrupted"]


async def test_without_the_table_the_checks_are_skipped_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeJobRepository()
    repository.column_dimension = None
    stuck = stored_job(status="processing")
    repository.by_id[stuck.id] = stuck

    with caplog.at_level(logging.WARNING):
        await run_job_startup_checks(repository, _settings(embedding_dimension=1))  # type: ignore[arg-type]

    assert "skipped" in caplog.text
    assert repository.by_id[stuck.id].status == "processing"


async def test_an_unreachable_database_only_skips_the_checks(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(_settings: Settings) -> object:
        raise ConnectionRefusedError("postgres://u:secret@host/db")

    monkeypatch.setattr("app.jobs.startup.get_sessionmaker", unreachable)

    with caplog.at_level(logging.WARNING):
        await run_jobs_startup(_settings())

    assert "not reachable" in caplog.text
    assert "secret" not in caplog.text


async def test_a_mismatch_is_not_swallowed_by_the_unreachable_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeJobRepository()

    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("app.jobs.startup.get_sessionmaker", lambda _s: lambda: Session())
    monkeypatch.setattr("app.jobs.startup.JobRepository", lambda _session: repository)

    with pytest.raises(EmbeddingDimensionMismatchError):
        await run_jobs_startup(_settings(embedding_dimension=768))
