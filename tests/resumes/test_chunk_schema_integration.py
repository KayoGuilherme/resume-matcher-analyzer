"""The vector column, the cosine query and the HNSW index against a real PostgreSQL."""

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
from app.resumes.models import Resume, ResumeChunk

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
        await connection.execute(text("DELETE FROM resume"))
    async with get_sessionmaker(settings)() as db_session:
        yield db_session
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM resume"))
    await engine.dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


def _resume() -> Resume:
    return Resume(
        id=uuid.uuid4(),
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        original_filename="r.pdf",
        file_type="pdf",
        size_bytes=1,
        page_count=1,
        text="t",
        parsing_metadata={},
        issues=[],
        created_at=datetime.now(UTC),
    )


def _vector(hot: int) -> list[float]:
    values = [0.0] * DIMENSION
    values[hot] = 1.0
    return values


def _chunk(resume_id: uuid.UUID, position: int, embedding: list[float]) -> ResumeChunk:
    return ResumeChunk(
        id=uuid.uuid4(),
        resume_id=resume_id,
        section="skills",
        experience_id=None,
        position=position,
        text=f"chunk {position}",
        embedding=embedding,
        embedding_model="bge-m3",
        created_at=datetime.now(UTC),
    )


async def test_a_vector_round_trips_and_a_new_resume_is_uploaded(session: AsyncSession) -> None:
    resume = _resume()
    session.add(resume)
    await session.commit()
    session.add(_chunk(resume.id, 0, _vector(3)))
    await session.commit()

    stored = (await session.execute(select(ResumeChunk))).scalar_one()
    status = (await session.execute(select(Resume.status))).scalar_one()

    assert len(stored.embedding) == DIMENSION
    assert stored.embedding[3] == 1.0
    assert stored.embedding_model == "bge-m3"
    assert status == "uploaded"


async def test_cosine_distance_orders_the_closest_chunk_first(session: AsyncSession) -> None:
    resume = _resume()
    session.add(resume)
    await session.commit()
    session.add_all([_chunk(resume.id, 0, _vector(1)), _chunk(resume.id, 1, _vector(2))])
    await session.commit()

    statement = (
        select(ResumeChunk.position)
        .order_by(ResumeChunk.embedding.cosine_distance(_vector(2)))
        .limit(2)
    )
    positions = (await session.execute(statement)).scalars().all()

    assert list(positions) == [1, 0]


async def test_the_cosine_query_can_use_the_hnsw_index(session: AsyncSession) -> None:
    resume = _resume()
    session.add(resume)
    await session.commit()
    session.add(_chunk(resume.id, 0, _vector(1)))
    await session.commit()
    literal = "[" + ",".join(str(value) for value in _vector(1)) + "]"

    await session.execute(text("SET LOCAL enable_seqscan = off"))
    query = text(
        "EXPLAIN SELECT id FROM resume_chunk ORDER BY embedding <=> CAST(:v AS vector) LIMIT 1"
    )
    plan = (await session.execute(query, {"v": literal})).scalars()

    assert "ix_resume_chunk_embedding" in "\n".join(plan)


async def test_deleting_a_resume_deletes_its_chunks(session: AsyncSession) -> None:
    resume = _resume()
    session.add(resume)
    await session.commit()
    session.add(_chunk(resume.id, 0, _vector(1)))
    await session.commit()

    await session.execute(text("DELETE FROM resume"))
    await session.commit()

    remaining = (await session.execute(text("SELECT count(*) FROM resume_chunk"))).scalar_one()
    assert remaining == 0


async def test_the_status_check_rejects_unknown_values(session: AsyncSession) -> None:
    resume = _resume()
    resume.status = "bogus"
    session.add(resume)

    with pytest.raises(IntegrityError, match="ck_resume_status"):
        await session.commit()
