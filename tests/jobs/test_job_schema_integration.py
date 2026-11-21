"""The job tables, the vector column and the HNSW index against a real PostgreSQL."""

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.jobs.models import Job, JobRequirement

pytestmark = pytest.mark.integration

DIMENSION = 1024


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    if not os.environ.get("DATABASE_URL"):
        pytest.fail("DATABASE_URL must be set for integration tests")
    get_settings.cache_clear()
    settings = get_settings()
    engine = get_engine(settings)
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM job"))
    async with get_sessionmaker(settings)() as db_session:
        yield db_session
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM job"))
    await engine.dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


def _job() -> Job:
    return Job(
        id=uuid.uuid4(),
        title="Backend",
        company=None,
        description="d",
        requirements_text=None,
        created_at=datetime.now(UTC),
    )


def _vector(hot: int) -> list[float]:
    values = [0.0] * DIMENSION
    values[hot] = 1.0
    return values


def _requirement(job_id: uuid.UUID, position: int, hot: int, **override: object) -> JobRequirement:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "job_id": job_id,
        "position": position,
        "text": f"requirement {position}",
        "category": "skill",
        "priority": "must_have",
        "priority_unclear": False,
        "min_years": None,
        "keywords": [{"name": "Python", "normalized": "python", "synonyms": []}],
        "source_text": "Python is required",
        "embedding": _vector(hot),
        "embedding_model": "bge-m3",
        "created_at": datetime.now(UTC),
    }
    values.update(override)
    return JobRequirement(**values)


async def test_a_job_and_a_requirement_round_trip(session: AsyncSession) -> None:
    job = _job()
    session.add(job)
    await session.commit()
    session.add(_requirement(job.id, 0, 3, min_years=2.5))
    await session.commit()

    stored = (await session.execute(select(JobRequirement))).scalar_one()
    status = (await session.execute(select(Job.status))).scalar_one()

    assert len(stored.embedding) == DIMENSION and stored.embedding[3] == 1.0
    assert (stored.min_years, stored.keywords[0]["normalized"]) == (2.5, "python")
    assert status == "uploaded"


async def test_cosine_distance_orders_the_closest_requirement_first(session: AsyncSession) -> None:
    job = _job()
    session.add(job)
    await session.commit()
    session.add_all([_requirement(job.id, 0, 1), _requirement(job.id, 1, 2)])
    await session.commit()

    statement = (
        select(JobRequirement.position)
        .order_by(JobRequirement.embedding.cosine_distance(_vector(2)))
        .limit(2)
    )

    assert list((await session.execute(statement)).scalars()) == [1, 0]


async def test_the_cosine_query_can_use_the_hnsw_index(session: AsyncSession) -> None:
    job = _job()
    session.add(job)
    await session.commit()
    session.add(_requirement(job.id, 0, 1))
    await session.commit()
    literal = "[" + ",".join(str(v) for v in _vector(1)) + "]"

    await session.execute(text("SET LOCAL enable_seqscan = off"))
    query = text(
        "EXPLAIN SELECT id FROM job_requirements ORDER BY embedding <=> CAST(:v AS vector) LIMIT 1"
    )
    plan = (await session.execute(query, {"v": literal})).scalars()

    assert "ix_job_requirements_embedding" in "\n".join(plan)


async def test_deleting_a_job_deletes_its_requirements(session: AsyncSession) -> None:
    job = _job()
    session.add(job)
    await session.commit()
    session.add(_requirement(job.id, 0, 1))
    await session.commit()

    await session.execute(text("DELETE FROM job"))
    await session.commit()

    count = (await session.execute(text("SELECT count(*) FROM job_requirements"))).scalar_one()
    assert count == 0


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ({"category": "bogus"}, "ck_job_requirements_category"),
        ({"priority": "maybe"}, "ck_job_requirements_priority"),
    ],
)
async def test_the_check_constraints_reject_unknown_values(
    session: AsyncSession, override: dict[str, object], constraint: str
) -> None:
    job = _job()
    session.add(job)
    await session.commit()
    session.add(_requirement(job.id, 0, 1, **override))

    with pytest.raises(IntegrityError, match=constraint):
        await session.commit()


async def test_a_bad_job_status_is_rejected(session: AsyncSession) -> None:
    job = _job()
    job.status = "bogus"
    session.add(job)

    with pytest.raises(IntegrityError, match="ck_job_status"):
        await session.commit()


async def test_positions_are_unique_per_job(session: AsyncSession) -> None:
    job = _job()
    session.add(job)
    await session.commit()
    session.add_all([_requirement(job.id, 0, 1), _requirement(job.id, 0, 2)])

    with pytest.raises(IntegrityError, match="uq_job_requirements_job_position"):
        await session.commit()
