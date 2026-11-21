"""The analysis table against a real PostgreSQL: constraints, the partial unique index, cascades."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.models import Analysis
from tests.analyses.support import analysis_row, clean_session, job_row, resume_row

pytestmark = pytest.mark.integration


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    async for db_session in clean_session():
        yield db_session


async def _stored_pair(session: AsyncSession):  # type: ignore[no-untyped-def]
    resume, job = resume_row(), job_row()
    session.add_all([resume, job])
    await session.commit()
    return resume, job


async def test_an_analysis_with_a_json_result_round_trips(session: AsyncSession) -> None:
    resume, job = await _stored_pair(session)
    result = {"findings": [{"verdict": "met", "evidence": [{"quote": "Python é ótimo"}]}]}
    session.add(analysis_row(resume.id, job.id, status="ready", result=result))
    await session.commit()

    stored = (await session.execute(select(Analysis))).scalar_one()

    assert stored.result == result and stored.status == "ready"
    assert stored.completed_at is None and stored.error_code is None


async def test_a_second_active_analysis_with_the_same_key_is_rejected(
    session: AsyncSession,
) -> None:
    resume, job = await _stored_pair(session)
    session.add(analysis_row(resume.id, job.id, status="processing", cache_key="k"))
    await session.commit()
    session.add(analysis_row(resume.id, job.id, status="ready", cache_key="k"))

    with pytest.raises(IntegrityError):
        await session.commit()


async def test_a_ready_analysis_also_blocks_a_new_active_one(session: AsyncSession) -> None:
    resume, job = await _stored_pair(session)
    session.add(analysis_row(resume.id, job.id, status="ready", cache_key="k"))
    await session.commit()
    session.add(analysis_row(resume.id, job.id, status="processing", cache_key="k"))

    with pytest.raises(IntegrityError):
        await session.commit()


async def test_failed_analyses_do_not_block_a_new_one(session: AsyncSession) -> None:
    resume, job = await _stored_pair(session)
    session.add_all(
        [
            analysis_row(resume.id, job.id, status="failed", cache_key="k"),
            analysis_row(resume.id, job.id, status="failed", cache_key="k"),
            analysis_row(resume.id, job.id, status="processing", cache_key="k"),
        ]
    )

    await session.commit()

    count = (await session.execute(text("SELECT count(*) FROM analysis"))).scalar_one()
    assert count == 3


async def test_different_keys_can_both_be_active(session: AsyncSession) -> None:
    resume, job = await _stored_pair(session)
    session.add_all(
        [
            analysis_row(resume.id, job.id, status="ready", cache_key="a"),
            analysis_row(resume.id, job.id, status="ready", cache_key="b"),
        ]
    )

    await session.commit()


async def test_deleting_the_resume_deletes_its_analyses(session: AsyncSession) -> None:
    resume, job = await _stored_pair(session)
    session.add(analysis_row(resume.id, job.id))
    await session.commit()

    await session.execute(text("DELETE FROM resume"))
    await session.commit()

    assert (await session.execute(text("SELECT count(*) FROM analysis"))).scalar_one() == 0
    assert (await session.execute(text("SELECT count(*) FROM job"))).scalar_one() == 1


async def test_deleting_the_job_deletes_its_analyses(session: AsyncSession) -> None:
    resume, job = await _stored_pair(session)
    session.add(analysis_row(resume.id, job.id))
    await session.commit()

    await session.execute(text("DELETE FROM job"))
    await session.commit()

    assert (await session.execute(text("SELECT count(*) FROM analysis"))).scalar_one() == 0
    assert (await session.execute(text("SELECT count(*) FROM resume"))).scalar_one() == 1


@pytest.mark.parametrize("status", ["uploaded", "done", ""])
async def test_a_bad_status_is_rejected_by_its_check_constraint(
    session: AsyncSession, status: str
) -> None:
    resume, job = await _stored_pair(session)
    session.add(analysis_row(resume.id, job.id, status=status))

    with pytest.raises(IntegrityError):
        await session.commit()


async def test_an_analysis_needs_an_existing_resume_and_job(session: AsyncSession) -> None:
    resume, _ = await _stored_pair(session)
    session.add(analysis_row(resume.id, job_row().id))

    with pytest.raises(IntegrityError):
        await session.commit()
