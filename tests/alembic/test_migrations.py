import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load_migration(revision: str) -> ModuleType:
    path = next(VERSIONS.glob(f"*-{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"migration_{revision}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_first_migration() -> ModuleType:
    return _load_migration("0001")


def test_first_migration_is_the_root_revision() -> None:
    module = _load_first_migration()

    assert module.revision == "0001"
    assert module.down_revision is None


def test_upgrade_enables_pgvector_idempotently(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_first_migration()
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append)

    module.upgrade()

    assert executed == ["CREATE EXTENSION IF NOT EXISTS vector"]


def test_downgrade_drops_pgvector(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_first_migration()
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append)

    module.downgrade()

    assert executed == ["DROP EXTENSION IF EXISTS vector"]


def test_second_migration_follows_the_first() -> None:
    module = _load_migration("0002")

    assert module.revision == "0002"
    assert module.down_revision == "0001"


def test_upgrade_creates_the_single_row_profile_table(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_migration("0002")
    created: list[tuple[object, ...]] = []
    monkeypatch.setattr(module.op, "create_table", lambda *items: created.append(items))

    module.upgrade()

    (items,) = created
    assert items[0] == "candidate_profile"
    columns = {item.name for item in items[1:] if isinstance(item, sa.Column)}
    assert columns == {
        "id",
        "target_role",
        "seniority",
        "total_years_coding",
        "stacks",
        "languages",
        "notable_facts",
    }
    checks = [str(item.sqltext) for item in items[1:] if isinstance(item, sa.CheckConstraint)]
    assert checks == ["id = 1"]


def test_downgrade_drops_the_profile_table(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_migration("0002")
    dropped: list[str] = []
    monkeypatch.setattr(module.op, "drop_table", dropped.append)

    module.downgrade()

    assert dropped == ["candidate_profile"]


def test_third_migration_follows_the_second() -> None:
    module = _load_migration("0003")

    assert module.revision == "0003"
    assert module.down_revision == "0002"


def test_upgrade_creates_the_resume_table_with_a_unique_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_migration("0003")
    created: list[tuple[object, ...]] = []
    monkeypatch.setattr(module.op, "create_table", lambda *items: created.append(items))

    module.upgrade()

    (items,) = created
    assert items[0] == "resume"
    columns = {item.name: item for item in items[1:] if isinstance(item, sa.Column)}
    assert set(columns) == {
        "id",
        "sha256",
        "original_filename",
        "file_type",
        "size_bytes",
        "page_count",
        "text",
        "parsing_metadata",
        "issues",
        "created_at",
    }
    assert {name for name, column in columns.items() if column.nullable} == {"page_count"}
    uniques = [item for item in items[1:] if isinstance(item, sa.UniqueConstraint)]
    assert [unique.name for unique in uniques] == ["uq_resume_sha256"]


def test_downgrade_drops_the_resume_table(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_migration("0003")
    dropped: list[str] = []
    monkeypatch.setattr(module.op, "drop_table", dropped.append)

    module.downgrade()

    assert dropped == ["resume"]


def test_fourth_migration_follows_the_third() -> None:
    module = _load_migration("0004")

    assert module.revision == "0004"
    assert module.down_revision == "0003"


def test_upgrade_adds_status_columns_and_the_chunk_table(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_migration("0004")
    added: list[str] = []
    created: list[tuple[object, ...]] = []
    sql: list[str] = []
    monkeypatch.setattr(module.op, "add_column", lambda _table, column: added.append(column.name))
    monkeypatch.setattr(module.op, "create_check_constraint", lambda *_a, **_k: None)
    monkeypatch.setattr(module.op, "create_table", lambda *items: created.append(items))
    monkeypatch.setattr(module.op, "create_index", lambda *_a, **_k: None)
    monkeypatch.setattr(module.op, "execute", sql.append)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/x")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "768")

    module.upgrade()

    assert added == ["status", "error_code", "error_message", "extraction"]
    (items,) = created
    assert items[0] == "resume_chunk"
    columns = {item.name: item for item in items[1:] if isinstance(item, sa.Column)}
    assert set(columns) == {
        "id",
        "resume_id",
        "section",
        "experience_id",
        "position",
        "text",
        "embedding",
        "embedding_model",
        "created_at",
    }
    assert columns["embedding"].type.dim == 768  # type: ignore[attr-defined]
    assert columns["experience_id"].nullable
    assert len(sql) == 1
    assert "USING hnsw (embedding vector_cosine_ops)" in sql[0]


def test_downgrade_removes_the_chunk_table_and_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_migration("0004")
    calls: list[str] = []
    monkeypatch.setattr(module.op, "drop_table", lambda name: calls.append(f"table:{name}"))
    monkeypatch.setattr(module.op, "drop_constraint", lambda *_a, **_k: calls.append("constraint"))
    monkeypatch.setattr(module.op, "drop_column", lambda _t, name: calls.append(f"column:{name}"))

    module.downgrade()

    assert calls[0] == "table:resume_chunk"
    assert set(calls[1:]) == {
        "constraint",
        "column:status",
        "column:error_code",
        "column:error_message",
        "column:extraction",
    }
