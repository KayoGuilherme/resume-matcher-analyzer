"""Jobs against a real PostgreSQL with pgvector (migrations applied), fakes for the AI."""

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import get_embedding_client
from app.ai.embeddings.dimension import EmbeddingDimensionMismatchError
from app.ai.embeddings.fake import FakeEmbeddingClient
from app.ai.llm import get_llm_client
from app.ai.llm.fake import FakeLLMClient
from app.ai.pipeline import ProcessedJob, process_job_text
from app.core.config import Settings, get_settings
from app.core.db import get_engine, get_sessionmaker
from app.core.logging import configure_logging
from app.core.processing import PROCESSING_MESSAGES
from app.jobs.repository import JobRepository
from app.jobs.router import get_job_background_service_factory
from app.jobs.service import JobService
from app.jobs.startup import run_jobs_startup
from app.main import create_app
from tests.fixtures.job_postings import ENGLISH, PORTUGUESE, Posting
from tests.jobs.support import job_from

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 21, tzinfo=UTC)


@pytest.fixture
async def settings() -> AsyncGenerator[Settings]:
    if not os.environ.get("DATABASE_URL"):
        pytest.fail("DATABASE_URL must be set for integration tests")
    get_settings.cache_clear()
    current = get_settings()
    engine = get_engine(current)

    async def clear() -> None:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM job"))

    await clear()
    yield current
    await clear()
    await engine.dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


@asynccontextmanager
async def _repository(settings: Settings) -> AsyncIterator[JobRepository]:
    async with get_sessionmaker(settings)() as session:
        yield JobRepository(session)


async def _add(
    settings: Settings, posting: Posting = ENGLISH, status: str = "uploaded"
) -> uuid.UUID:
    job = job_from(posting, status)
    async with _repository(settings) as repository:
        await repository.add(job)
    return job.id


async def _processed(posting: Posting = ENGLISH, dimension: int = 1024) -> ProcessedJob:
    return await process_job_text(
        posting.text,
        FakeLLMClient(list(posting.answers)),
        FakeEmbeddingClient(dimension, "fake-bge"),
        NOW,
    )


async def _rows(session: AsyncSession, job_id: uuid.UUID) -> list[tuple[str, str, str, bool]]:
    result = await session.execute(
        text(
            "SELECT text, category, priority, priority_unclear FROM job_requirements "
            "WHERE job_id = :id ORDER BY position"
        ),
        {"id": job_id},
    )
    return [tuple(row) for row in result]  # type: ignore[misc]


# --- repository -----------------------------------------------------------------------------------


async def test_add_get_and_list_round_trip(settings: Settings) -> None:
    job_id = await _add(settings)

    async with _repository(settings) as repository:
        job = await repository.get(job_id)
        (item,) = await repository.list_all()

    assert job is not None and job.id == job_id
    assert (job.status, job.error, job.extraction) == ("uploaded", None, None)
    assert job.description == ENGLISH.text and job.company == "ACME"
    assert not hasattr(item, "description")
    assert (item.id, item.title, item.status) == (job_id, "Backend Engineer", "uploaded")


async def test_two_concurrent_starts_have_exactly_one_winner(settings: Settings) -> None:
    job_id = await _add(settings)

    async def start() -> bool:
        async with _repository(settings) as repository:
            return await repository.begin_processing(job_id)

    results = await asyncio.gather(*[start() for _ in range(5)])

    assert sorted(results) == [False, False, False, False, True]


async def test_starting_an_unknown_job_reports_false(settings: Settings) -> None:
    async with _repository(settings) as repository:
        assert await repository.begin_processing(uuid.uuid4()) is False


async def test_saving_stores_the_extraction_and_the_rows_and_replaces_older_ones(
    settings: Settings,
) -> None:
    job_id = await _add(settings)
    first = await _processed(ENGLISH)
    second = await _processed(ENGLISH)
    async with _repository(settings) as repository:
        await repository.begin_processing(job_id)
        assert await repository.save_processed(job_id, first)
        stored_first = await repository.get(job_id)
        await repository.begin_processing(job_id)
        assert await repository.save_processed(job_id, second)

    assert stored_first is not None and stored_first.status == "ready"
    assert stored_first.extraction == first.extraction
    async with get_sessionmaker(settings)() as session:
        ids = (
            await session.execute(
                text("SELECT id FROM job_requirements WHERE job_id = :id"), {"id": job_id}
            )
        ).scalars()
        models = (
            await session.execute(
                text("SELECT DISTINCT embedding_model FROM job_requirements WHERE job_id = :id"),
                {"id": job_id},
            )
        ).scalars()
        assert set(ids) == {r.requirement.id for r in second.requirements}
        assert list(models) == ["fake-bge"]
        assert len(await _rows(session, job_id)) == len(ENGLISH.requirements)


async def test_a_failure_inside_the_save_rolls_everything_back(settings: Settings) -> None:
    job_id = await _add(settings)
    async with _repository(settings) as repository:
        await repository.begin_processing(job_id)
        await repository.save_processed(job_id, await _processed(ENGLISH))
        await repository.begin_processing(job_id)
        broken = await _processed(PORTUGUESE)
        broken.requirements[0].embedding.pop()  # 1023 numbers: refused by the column

        with pytest.raises(Exception, match="dimension"):
            await repository.save_processed(job_id, broken)

        kept = await repository.get(job_id)

    assert kept is not None and kept.status == "processing"
    async with get_sessionmaker(settings)() as session:
        texts = [row[0] for row in await _rows(session, job_id)]
    assert texts == [s[1] for s in ENGLISH.requirements]


async def test_saving_for_a_deleted_job_writes_nothing(settings: Settings) -> None:
    async with _repository(settings) as repository:
        assert await repository.save_processed(uuid.uuid4(), await _processed()) is False


async def test_set_failed_keeps_the_previous_extraction_and_rows(settings: Settings) -> None:
    job_id = await _add(settings)
    async with _repository(settings) as repository:
        await repository.save_processed(job_id, await _processed())
        await repository.begin_processing(job_id)
        await repository.set_failed(job_id, "llm_timeout", "msg")
        loaded = await repository.get(job_id)

    assert loaded is not None and loaded.error is not None
    assert (loaded.status, loaded.error.code) == ("failed", "llm_timeout")
    assert loaded.extraction is not None
    async with get_sessionmaker(settings)() as session:
        assert len(await _rows(session, job_id)) == len(ENGLISH.requirements)


async def test_starting_again_clears_the_error(settings: Settings) -> None:
    job_id = await _add(settings)
    async with _repository(settings) as repository:
        await repository.set_failed(job_id, "llm_timeout", "msg")
        await repository.begin_processing(job_id)
        loaded = await repository.get(job_id)

    assert loaded is not None and (loaded.status, loaded.error) == ("processing", None)


async def test_deleting_removes_the_job_and_its_rows(settings: Settings) -> None:
    job_id = await _add(settings)
    async with _repository(settings) as repository:
        await repository.save_processed(job_id, await _processed())
        assert await repository.delete(job_id) is True
        assert await repository.delete(job_id) is False

    async with get_sessionmaker(settings)() as session:
        assert await _rows(session, job_id) == []


async def test_the_dimension_is_read_from_the_catalog(settings: Settings) -> None:
    async with _repository(settings) as repository:
        assert await repository.requirements_embedding_dimension() == 1024


# --- startup --------------------------------------------------------------------------------------


async def test_startup_accepts_a_matching_dimension_and_recovers_interrupted_jobs(
    settings: Settings,
) -> None:
    stuck = await _add(settings, status="processing")
    fine = await _add(settings, status="ready")

    await run_jobs_startup(settings)

    async with _repository(settings) as repository:
        recovered = await repository.get(stuck)
        untouched = await repository.get(fine)
    assert recovered is not None and recovered.error is not None
    assert (recovered.status, recovered.error.code) == ("failed", "processing_interrupted")
    assert recovered.error.message == PROCESSING_MESSAGES["processing_interrupted"]
    assert untouched is not None and untouched.status == "ready"


async def test_startup_refuses_a_mismatching_dimension(settings: Settings) -> None:
    mismatching = Settings(database_url=settings.database_url, embedding_dimension=768)

    with pytest.raises(EmbeddingDimensionMismatchError, match="768.*job_requirements.*1024"):
        await run_jobs_startup(mismatching)


# --- end to end -----------------------------------------------------------------------------------


@pytest.mark.parametrize("posting", [ENGLISH, PORTUGUESE], ids=["english", "portuguese"])
async def test_the_whole_flow_with_fakes_and_no_content_in_debug_logs(
    settings: Settings, caplog: pytest.LogCaptureFixture, posting: Posting
) -> None:
    app = create_app()
    llm = FakeLLMClient(list(posting.answers))
    embedder = FakeEmbeddingClient(1024)

    @asynccontextmanager
    async def factory() -> AsyncIterator[JobService]:
        async with _repository(settings) as repository:
            yield JobService(repository)

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_embedding_client] = lambda: embedder
    app.dependency_overrides[get_job_background_service_factory] = lambda: factory
    configure_logging("DEBUG")
    caplog.set_level(logging.DEBUG)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/jobs",
                json={"title": "Secret Title", "company": "Secret Co", "description": posting.text},
            )
        ).json()
        started = await client.post(f"/jobs/{created['id']}/process")
        fetched = (await client.get(f"/jobs/{created['id']}")).json()
        job_id = uuid.UUID(created["id"])
        async with get_sessionmaker(settings)() as session:
            rows = await _rows(session, job_id)
            nearest = (
                await session.execute(
                    text(
                        "SELECT text FROM job_requirements WHERE job_id = :id "
                        "ORDER BY embedding <=> CAST(:v AS vector) LIMIT 1"
                    ),
                    {
                        "id": job_id,
                        "v": "["
                        + ",".join(
                            str(v) for v in (await embedder.embed([posting.requirements[2][1]]))[0]
                        )
                        + "]",
                    },
                )
            ).scalar_one()
        deleted = await client.delete(f"/jobs/{created['id']}")
        async with get_sessionmaker(settings)() as session:
            remaining = await _rows(session, job_id)

    assert (created["status"], started.status_code, fetched["status"]) == ("uploaded", 202, "ready")
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        (s[1], s[2], s[3], s[5]) for s in posting.requirements
    ]
    assert nearest == posting.requirements[2][1]
    assert deleted.status_code == 204 and remaining == []
    logged = " ".join(str(r.__dict__) + r.getMessage() for r in caplog.records)
    for fragment in (
        "Secret Title",
        "Secret Co",
        posting.requirements[0][0],
        posting.responsibilities[0],
    ):
        assert fragment not in logged
