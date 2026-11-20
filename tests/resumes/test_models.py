from sqlalchemy import UniqueConstraint

import app.resumes.models  # noqa: F401  (registers the table on Base.metadata)
from app.core.db import Base
from app.resumes.models import Resume


def test_model_is_registered_on_the_declarative_base() -> None:
    assert Base.metadata.tables["resume"] is Resume.__table__


def test_sha256_is_unique() -> None:
    uniques = [
        [column.name for column in constraint.columns]
        for constraint in Resume.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]

    assert uniques == [["sha256"]]


def test_only_page_count_is_nullable() -> None:
    nullable = {column.name for column in Resume.__table__.columns if column.nullable}

    assert nullable == {"page_count"}


def test_primary_key_is_the_id() -> None:
    assert [column.name for column in Resume.__table__.primary_key.columns] == ["id"]
