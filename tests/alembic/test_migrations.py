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
