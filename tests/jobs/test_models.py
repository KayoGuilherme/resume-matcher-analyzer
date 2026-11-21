from sqlalchemy import CheckConstraint, UniqueConstraint

import app.jobs.models  # noqa: F401  (registers the tables on Base.metadata)
from app.core.db import Base
from app.jobs.models import Job, JobRequirement


def test_models_are_registered_on_the_declarative_base() -> None:
    assert Base.metadata.tables["job"] is Job.__table__
    assert Base.metadata.tables["job_requirements"] is JobRequirement.__table__


def test_job_nullable_columns() -> None:
    nullable = {c.name for c in Job.__table__.columns if c.nullable}

    assert nullable == {"company", "requirements_text", "error_code", "error_message", "extraction"}


def test_requirement_nullable_columns() -> None:
    assert {c.name for c in JobRequirement.__table__.columns if c.nullable} == {"min_years"}


def test_requirements_belong_to_a_job_and_are_deleted_with_it() -> None:
    (foreign_key,) = JobRequirement.__table__.foreign_keys

    assert foreign_key.column is Job.__table__.c.id
    assert foreign_key.ondelete == "CASCADE"


def test_the_embedding_has_an_hnsw_cosine_index() -> None:
    (index,) = [
        i for i in JobRequirement.__table__.indexes if i.name == "ix_job_requirements_embedding"
    ]

    assert index.dialect_options["postgresql"]["using"] == "hnsw"
    assert index.dialect_options["postgresql"]["ops"] == {"embedding": "vector_cosine_ops"}


def test_positions_are_unique_per_job() -> None:
    uniques = [
        [c.name for c in constraint.columns]
        for constraint in JobRequirement.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]

    assert ["job_id", "position"] in uniques


def test_status_category_and_priority_are_constrained() -> None:
    names = {
        constraint.name
        for table in (Job.__table__, JobRequirement.__table__)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert {
        "ck_job_status",
        "ck_job_requirements_category",
        "ck_job_requirements_priority",
    } <= names
