"""Processing against a real PostgreSQL with pgvector (migrations applied), fakes for the AI."""

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import get_embedding_client
from app.ai.embeddings.dimension import EmbeddingDimensionMismatchError
from app.ai.embeddings.fake import FakeEmbeddingClient
from app.ai.llm import get_llm_client
from app.ai.llm.fake import FakeLLMClient
from app.ai.pipeline import ProcessedResume, process_resume_text
from app.core.config import Settings, get_settings
from app.core.db import get_engine, get_sessionmaker
from app.core.logging import configure_logging
from app.core.processing import PROCESSING_MESSAGES
from app.main import create_app
from app.resumes.repository import ResumeRepository
from app.resumes.router import get_background_service_factory
from app.resumes.service import ResumeService
from app.resumes.startup import run_startup
from tests.ai.extraction.builders import RESUME_TEXT, experience, extracted
from tests.fixtures import documents
from tests.resumes.processing import stored_resume

pytestmark = pytest.mark.integration

GOOD = "Reduced p95 latency by 40%"
WRAPPED = "Built a payments API with Spring Boot and PostgreSQL"
PDF_BULLET = "Mentored four junior developers and led weekly code reviews for the whole team."
NOW = datetime(2026, 11, 20, tzinfo=UTC)


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
            await connection.execute(text("DELETE FROM resume"))

    await clear()
    yield current
    await clear()
    await engine.dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


@asynccontextmanager
async def _repository(settings: Settings) -> AsyncIterator[ResumeRepository]:
    async with get_sessionmaker(settings)() as session:
        yield ResumeRepository(session)


async def _add(settings: Settings, status: str = "uploaded") -> uuid.UUID:
    resume = stored_resume(status=status)
    async with _repository(settings) as repository:
        assert await repository.add(resume)
    return resume.id


async def _processed(*bullets: str, skills: list[str] | None = None) -> ProcessedResume:
    llm = FakeLLMClient(
        [extracted(experiences=[experience(*bullets)], skills=skills or ["Cloud: AWS, Docker"])]
    )
    return await process_resume_text(RESUME_TEXT, llm, FakeEmbeddingClient(1024, "fake-bge"), NOW)


async def _chunk_texts(session: AsyncSession, resume_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        text("SELECT text FROM resume_chunk WHERE resume_id = :id ORDER BY position"),
        {"id": resume_id},
    )
    return list(rows.scalars())


async def test_two_concurrent_starts_have_exactly_one_winner(settings: Settings) -> None:
    resume_id = await _add(settings)

    async def start() -> bool:
        async with _repository(settings) as repository:
            return await repository.begin_processing(resume_id)

    results = await asyncio.gather(*[start() for _ in range(5)])

    assert sorted(results) == [False, False, False, False, True]


async def test_starting_an_unknown_resume_reports_false(settings: Settings) -> None:
    async with _repository(settings) as repository:
        assert await repository.begin_processing(uuid.uuid4()) is False


async def test_saving_stores_the_extraction_the_chunks_and_replaces_older_ones(
    settings: Settings,
) -> None:
    resume_id = await _add(settings)
    async with _repository(settings) as repository:
        await repository.begin_processing(resume_id)
        assert await repository.save_processed(resume_id, await _processed(GOOD, WRAPPED))
        first = await repository.get(resume_id)
        await repository.begin_processing(resume_id)
        assert await repository.save_processed(resume_id, await _processed(GOOD))
        second = await repository.get(resume_id)

    assert first is not None and second is not None
    assert (first.status, first.error) == ("ready", None)
    assert first.extraction is not None
    assert first.extraction.resume.experiences[0].bullets == [GOOD, WRAPPED]
    assert second.extraction is not None
    assert second.extraction.resume.experiences[0].bullets == [GOOD]
    async with get_sessionmaker(settings)() as session:
        assert await _chunk_texts(session, resume_id) == ["Cloud: AWS, Docker", GOOD]
        models = (
            await session.execute(
                text("SELECT DISTINCT embedding_model FROM resume_chunk WHERE resume_id = :id"),
                {"id": resume_id},
            )
        ).scalars()
        assert list(models) == ["fake-bge"]


async def test_the_extraction_round_trips_through_the_database(settings: Settings) -> None:
    resume_id = await _add(settings)
    processed = await _processed(GOOD)
    async with _repository(settings) as repository:
        await repository.save_processed(resume_id, processed)
        loaded = await repository.get(resume_id)

    assert loaded is not None
    assert loaded.extraction == processed.extraction


async def test_a_failure_inside_the_save_rolls_everything_back(settings: Settings) -> None:
    resume_id = await _add(settings)
    async with _repository(settings) as repository:
        await repository.begin_processing(resume_id)
        await repository.save_processed(resume_id, await _processed(GOOD))
        await repository.begin_processing(resume_id)
        broken = await _processed(GOOD)
        broken.chunks[0].embedding.pop()  # a vector of 1023 numbers is refused by the column

        with pytest.raises(Exception, match="dimension"):
            await repository.save_processed(resume_id, broken)

        kept = await repository.get(resume_id)

    assert kept is not None
    assert kept.status == "processing"  # the failed transaction changed nothing
    async with get_sessionmaker(settings)() as session:
        assert await _chunk_texts(session, resume_id) == ["Cloud: AWS, Docker", GOOD]


async def test_saving_for_a_deleted_resume_writes_nothing(settings: Settings) -> None:
    async with _repository(settings) as repository:
        assert await repository.save_processed(uuid.uuid4(), await _processed(GOOD)) is False


async def test_set_failed_keeps_the_previous_extraction_and_chunks(settings: Settings) -> None:
    resume_id = await _add(settings)
    async with _repository(settings) as repository:
        await repository.save_processed(resume_id, await _processed(GOOD))
        await repository.begin_processing(resume_id)
        await repository.set_failed(resume_id, "llm_timeout", "msg")
        loaded = await repository.get(resume_id)

    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.error is not None and loaded.error.code == "llm_timeout"
    assert loaded.extraction is not None
    async with get_sessionmaker(settings)() as session:
        assert len(await _chunk_texts(session, resume_id)) == 2


async def test_starting_again_clears_the_error(settings: Settings) -> None:
    resume_id = await _add(settings)
    async with _repository(settings) as repository:
        await repository.set_failed(resume_id, "llm_timeout", "msg")
        await repository.begin_processing(resume_id)
        loaded = await repository.get(resume_id)

    assert loaded is not None
    assert (loaded.status, loaded.error) == ("processing", None)


async def test_deleting_a_resume_removes_its_chunks(settings: Settings) -> None:
    resume_id = await _add(settings)
    async with _repository(settings) as repository:
        await repository.save_processed(resume_id, await _processed(GOOD))
        await repository.delete(resume_id)

    async with get_sessionmaker(settings)() as session:
        assert await _chunk_texts(session, resume_id) == []


async def test_the_list_shows_the_status_and_not_the_extraction(settings: Settings) -> None:
    resume_id = await _add(settings)
    async with _repository(settings) as repository:
        await repository.save_processed(resume_id, await _processed(GOOD))
        (item,) = await repository.list_all()

    assert item.status == "ready"
    assert not hasattr(item, "extraction")


async def test_the_column_dimension_is_read_from_the_catalog(settings: Settings) -> None:
    async with _repository(settings) as repository:
        assert await repository.chunk_embedding_dimension() == 1024


async def test_startup_accepts_a_matching_dimension_and_recovers_interrupted_resumes(
    settings: Settings,
) -> None:
    stuck = await _add(settings, status="processing")
    fine = await _add(settings, status="ready")

    await run_startup(settings)

    async with _repository(settings) as repository:
        recovered = await repository.get(stuck)
        untouched = await repository.get(fine)
    assert recovered is not None and recovered.error is not None
    assert (recovered.status, recovered.error.code) == ("failed", "processing_interrupted")
    assert recovered.error.message == PROCESSING_MESSAGES["processing_interrupted"]
    assert untouched is not None and untouched.status == "ready"


async def test_startup_refuses_a_mismatching_dimension(settings: Settings) -> None:
    mismatching = Settings(database_url=settings.database_url, embedding_dimension=768)

    with pytest.raises(EmbeddingDimensionMismatchError, match="768.*1024"):
        await run_startup(mismatching)


async def test_the_whole_flow_with_fakes_and_no_content_in_debug_logs(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app()
    llm = FakeLLMClient(
        [extracted(experiences=[experience(PDF_BULLET)], skills=["Backend Developer"])]
    )

    @asynccontextmanager
    async def factory() -> AsyncIterator[ResumeService]:
        async with _repository(settings) as repository:
            yield ResumeService(repository, None, 1)  # type: ignore[arg-type]

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient(1024)
    app.dependency_overrides[get_background_service_factory] = lambda: factory
    pdf = documents.clean_pdf()
    configure_logging("DEBUG")

    caplog.set_level(logging.DEBUG)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        uploaded = (
            await client.post("/resumes", files={"file": ("cv.pdf", pdf, "application/pdf")})
        ).json()
        started = await client.post(f"/resumes/{uploaded['id']}/process")
        fetched = (await client.get(f"/resumes/{uploaded['id']}")).json()
        deleted = await client.delete(f"/resumes/{uploaded['id']}")

    assert uploaded["status"] == "uploaded"
    assert started.status_code == 202
    assert fetched["status"] == "ready"
    assert deleted.status_code == 204
    async with get_sessionmaker(settings)() as session:
        count = (await session.execute(text("SELECT count(*) FROM resume_chunk"))).scalar_one()
    assert count == 0
    logged = " ".join(str(r.__dict__) + r.getMessage() for r in caplog.records)
    for fragment in (PDF_BULLET, "Backend Developer", "Acme", "cv.pdf"):
        assert fragment not in logged


async def test_the_chunks_come_back_in_resume_order_with_their_vectors(
    settings: Settings,
) -> None:
    resume_id = await _add(settings)
    async with _repository(settings) as repository:
        await repository.begin_processing(resume_id)
        assert await repository.save_processed(resume_id, await _processed(GOOD, WRAPPED))
        stored = await repository.get_chunks(resume_id)

    assert [c.text for c in stored.chunks] == ["Cloud: AWS, Docker", GOOD, WRAPPED]
    assert [c.position for c in stored.chunks] == [0, 1, 2]
    assert all(len(c.embedding) == 1024 for c in stored.chunks)
    assert all(isinstance(x, float) for x in stored.chunks[0].embedding)
    assert stored.embedding_models == {"fake-bge"}
    assert [c.section for c in stored.chunks] == ["skills", "experience", "experience"]


async def test_the_chunks_of_an_unknown_resume_are_empty(settings: Settings) -> None:
    async with _repository(settings) as repository:
        stored = await repository.get_chunks(uuid.uuid4())

    assert stored.chunks == [] and stored.embedding_models == set()


async def test_the_chunks_of_another_resume_are_not_mixed_in(settings: Settings) -> None:
    first, second = await _add(settings), await _add(settings)
    async with _repository(settings) as repository:
        for resume_id, bullet in ((first, GOOD), (second, WRAPPED)):
            await repository.begin_processing(resume_id)
            await repository.save_processed(resume_id, await _processed(bullet))
        stored = await repository.get_chunks(first)

    assert GOOD in [c.text for c in stored.chunks]
    assert WRAPPED not in [c.text for c in stored.chunks]
