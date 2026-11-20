from sqlalchemy import UniqueConstraint

import app.resumes.models  # noqa: F401  (registers the table on Base.metadata)
from app.core.db import Base
from app.resumes.models import Resume, ResumeChunk


def test_model_is_registered_on_the_declarative_base() -> None:
    assert Base.metadata.tables["resume"] is Resume.__table__


def test_sha256_is_unique() -> None:
    uniques = [
        [column.name for column in constraint.columns]
        for constraint in Resume.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]

    assert uniques == [["sha256"]]


def test_only_page_count_and_the_processing_results_are_nullable() -> None:
    nullable = {column.name for column in Resume.__table__.columns if column.nullable}

    assert nullable == {"page_count", "error_code", "error_message", "extraction"}


def test_chunks_belong_to_a_resume_and_are_deleted_with_it() -> None:
    (foreign_key,) = ResumeChunk.__table__.foreign_keys

    assert foreign_key.column is Resume.__table__.c.id
    assert foreign_key.ondelete == "CASCADE"


def test_chunk_embedding_has_an_hnsw_cosine_index() -> None:
    (index,) = [i for i in ResumeChunk.__table__.indexes if i.name == "ix_resume_chunk_embedding"]

    assert index.dialect_options["postgresql"]["using"] == "hnsw"
    assert index.dialect_options["postgresql"]["ops"] == {"embedding": "vector_cosine_ops"}


def test_primary_key_is_the_id() -> None:
    assert [column.name for column in Resume.__table__.primary_key.columns] == ["id"]
