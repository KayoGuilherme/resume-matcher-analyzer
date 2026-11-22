"""The analyses repository against a real PostgreSQL (migrations applied)."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.repository import AnalysisRepository
from app.analyses.schemas import AnalysisDetail
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from tests.analyses.results import a_result, a_stored_report
from tests.analyses.support import clean_session, job_row, resume_row

pytestmark = pytest.mark.integration


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    async for db_session in clean_session():
        yield db_session


@asynccontextmanager
async def _repository() -> AsyncIterator[AnalysisRepository]:
    async with get_sessionmaker(get_settings())() as db_session:
        yield AnalysisRepository(db_session)


async def _pair(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    resume, job = resume_row(), job_row()
    session.add_all([resume, job])
    await session.commit()
    return resume.id, job.id


def _new(resume_id: uuid.UUID, job_id: uuid.UUID) -> AnalysisDetail:
    return AnalysisDetail(
        id=uuid.uuid4(),
        resume_id=resume_id,
        job_id=job_id,
        status="processing",
        created_at=datetime.now(UTC),
    )


async def test_create_then_find_active_and_get(session: AsyncSession) -> None:
    resume_id, job_id = await _pair(session)
    analysis = _new(resume_id, job_id)

    async with _repository() as repository:
        stored, created = await repository.create(analysis, "k1")
        found = await repository.find_active("k1")
        fetched = await repository.get(analysis.id)

    assert created and stored.id == analysis.id
    assert found is not None and found.id == analysis.id and found.status == "processing"
    assert fetched == found
    async with _repository() as repository:
        assert await repository.find_active("other") is None
        assert await repository.get(uuid.uuid4()) is None


async def test_two_concurrent_creates_with_the_same_key_give_one_row_and_one_winner(
    session: AsyncSession,
) -> None:
    resume_id, job_id = await _pair(session)

    async def attempt() -> tuple[AnalysisDetail, bool]:
        async with _repository() as repository:
            return await repository.create(_new(resume_id, job_id), "same")

    results = await asyncio.gather(*[attempt() for _ in range(6)])

    assert sum(created for _, created in results) == 1
    assert len({analysis.id for analysis, _ in results}) == 1


async def test_a_failed_analysis_does_not_block_a_new_one(session: AsyncSession) -> None:
    resume_id, job_id = await _pair(session)
    first = _new(resume_id, job_id)

    async with _repository() as repository:
        await repository.create(first, "k")
        await repository.set_failed(first.id, "llm_timeout", "slow")
        second, created = await repository.create(_new(resume_id, job_id), "k")
        failed = await repository.get(first.id)

    assert created and second.id != first.id
    assert failed is not None and failed.status == "failed"


async def test_a_ready_analysis_is_returned_instead_of_a_new_one(session: AsyncSession) -> None:
    resume_id, job_id = await _pair(session)
    first = _new(resume_id, job_id)

    async with _repository() as repository:
        await repository.create(first, "k")
        await repository.save_result(first.id, a_result(), a_stored_report())
        again, created = await repository.create(_new(resume_id, job_id), "k")

    assert not created and again.id == first.id and again.status == "ready"


async def test_save_result_stores_the_result_and_completed_at(session: AsyncSession) -> None:
    resume_id, job_id = await _pair(session)
    analysis = _new(resume_id, job_id)

    async with _repository() as repository:
        await repository.create(analysis, "k")
        assert await repository.save_result(analysis.id, a_result(llm_calls=3), a_stored_report())
        stored = await repository.get(analysis.id)

    assert stored is not None and stored.status == "ready" and stored.error is None
    assert stored.completed_at is not None
    assert stored.result == a_result(llm_calls=3)


async def test_save_result_for_a_deleted_analysis_writes_nothing(session: AsyncSession) -> None:
    async with _repository() as repository:
        assert not await repository.save_result(uuid.uuid4(), a_result(), a_stored_report())


async def test_set_failed_stores_code_and_message_and_no_result(session: AsyncSession) -> None:
    resume_id, job_id = await _pair(session)
    analysis = _new(resume_id, job_id)

    async with _repository() as repository:
        await repository.create(analysis, "k")
        await repository.set_failed(analysis.id, "llm_unavailable", "Try again later.")
        stored = await repository.get(analysis.id)

    assert stored is not None and stored.status == "failed" and stored.result is None
    assert stored.error is not None
    assert (stored.error.code, stored.error.message) == ("llm_unavailable", "Try again later.")


async def test_mark_interrupted_only_touches_processing_analyses(session: AsyncSession) -> None:
    resume_id, job_id = await _pair(session)
    running, done = _new(resume_id, job_id), _new(resume_id, job_id)

    async with _repository() as repository:
        await repository.create(running, "a")
        await repository.create(done, "b")
        await repository.save_result(done.id, a_result(), a_stored_report())
        count = await repository.mark_interrupted("Interrupted.")
        interrupted = await repository.get(running.id)
        untouched = await repository.get(done.id)

    assert count == 1
    assert interrupted is not None and interrupted.error is not None
    assert (interrupted.status, interrupted.error.code) == ("failed", "processing_interrupted")
    assert untouched is not None and untouched.status == "ready"


async def test_the_result_round_trips_through_the_database_as_a_model(
    session: AsyncSession,
) -> None:
    resume_id, job_id = await _pair(session)
    analysis = _new(resume_id, job_id)
    result = a_result(llm_calls=2)

    async with _repository() as repository:
        await repository.create(analysis, "k")
        await repository.save_result(analysis.id, result, a_stored_report())
        stored = await repository.get(analysis.id)

    assert stored is not None and stored.result == result


async def test_a_saved_report_is_read_back_equal(session: AsyncSession) -> None:
    resume_id, job_id = await _pair(session)
    analysis = _new(resume_id, job_id)
    report = a_stored_report()

    async with _repository() as repository:
        await repository.create(analysis, "k-report")
        assert await repository.get_report(analysis.id) is None  # not ready yet
        assert await repository.save_result(analysis.id, a_result(), report)
        stored = await repository.get_report(analysis.id)
        detail = await repository.get(analysis.id)

    assert stored == report
    assert detail is not None and detail.status == "ready" and detail.result == a_result()


async def test_a_failed_analysis_has_no_report(session: AsyncSession) -> None:
    resume_id, job_id = await _pair(session)
    analysis = _new(resume_id, job_id)

    async with _repository() as repository:
        await repository.create(analysis, "k-failed")
        await repository.save_result(analysis.id, a_result(), a_stored_report())
        await repository.set_failed(analysis.id, "processing_failed", "Failed.")
        assert await repository.get_report(analysis.id) is None


async def test_the_report_of_an_unknown_analysis_is_none(session: AsyncSession) -> None:
    async with _repository() as repository:
        assert await repository.get_report(uuid.uuid4()) is None
