from sqlalchemy import CheckConstraint

import app.profile.models  # noqa: F401  (registers the table on Base.metadata)
from app.core.db import Base
from app.profile.models import CandidateProfile


def test_model_is_registered_on_the_declarative_base() -> None:
    assert Base.metadata.tables["candidate_profile"] is CandidateProfile.__table__


def test_table_allows_only_one_row() -> None:
    table = CandidateProfile.__table__
    checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]

    assert [str(c.sqltext) for c in checks] == ["id = 1"]
    assert [column.name for column in table.primary_key.columns] == ["id"]


def test_every_column_is_required() -> None:
    assert all(not column.nullable for column in CandidateProfile.__table__.columns)
