from sqlalchemy import CheckConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

import app.analyses.models  # noqa: F401  (registers the table on Base.metadata)
from app.analyses.models import Analysis
from app.core.db import Base


def test_the_model_is_registered_on_the_declarative_base() -> None:
    assert Base.metadata.tables["analysis"] is Analysis.__table__


def test_nullable_columns() -> None:
    nullable = {c.name for c in Analysis.__table__.columns if c.nullable}

    assert nullable == {"error_code", "error_message", "result", "completed_at"}


def test_an_analysis_is_deleted_with_its_resume_or_job() -> None:
    foreign_keys = {fk.column.table.name: fk.ondelete for fk in Analysis.__table__.foreign_keys}

    assert foreign_keys == {"resume": "CASCADE", "job": "CASCADE"}


def test_status_is_constrained() -> None:
    (constraint,) = [c for c in Analysis.__table__.constraints if isinstance(c, CheckConstraint)]

    assert constraint.name == "ck_analysis_status"
    assert "'processing', 'ready', 'failed'" in str(constraint.sqltext)


def test_one_active_analysis_per_cache_key_is_a_partial_unique_index() -> None:
    (index,) = [i for i in Analysis.__table__.indexes if i.name == "uq_analysis_cache_key_active"]

    assert index.unique
    statement = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "WHERE status IN ('processing', 'ready')" in statement


def test_the_resume_and_job_ids_are_indexed() -> None:
    indexed = {c.name for i in Analysis.__table__.indexes for c in i.columns}

    assert {"resume_id", "job_id", "cache_key"} <= indexed
