from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.storage import LocalFileStorage, get_file_storage


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path / "files")


async def test_save_then_read_round_trip(storage: LocalFileStorage) -> None:
    await storage.save("a.pdf", b"%PDF-bytes")

    assert await storage.read("a.pdf") == b"%PDF-bytes"


async def test_saving_the_same_key_overwrites(storage: LocalFileStorage) -> None:
    await storage.save("a.pdf", b"one")
    await storage.save("a.pdf", b"two")

    assert await storage.read("a.pdf") == b"two"


async def test_delete_removes_the_file_and_is_idempotent(storage: LocalFileStorage) -> None:
    await storage.save("a.pdf", b"x")

    await storage.delete("a.pdf")
    await storage.delete("a.pdf")

    assert not await storage.exists("a.pdf")


async def test_exists_reports_presence(storage: LocalFileStorage) -> None:
    assert not await storage.exists("a.pdf")

    await storage.save("a.pdf", b"x")

    assert await storage.exists("a.pdf")


async def test_directory_is_created_on_first_write_only(tmp_path: Path) -> None:
    root = tmp_path / "nested" / "files"
    storage = LocalFileStorage(root)
    assert not root.exists()

    await storage.save("a.pdf", b"x")

    assert root.is_dir()


async def test_no_temporary_files_are_left_after_a_write(
    storage: LocalFileStorage, tmp_path: Path
) -> None:
    await storage.save("a.pdf", b"x")

    assert [p.name for p in (tmp_path / "files").iterdir()] == ["a.pdf"]


async def test_failed_write_leaves_nothing_behind(
    storage: LocalFileStorage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("app.core.storage.os.replace", boom)

    with pytest.raises(OSError, match="disk full"):
        await storage.save("a.pdf", b"x")

    assert list((tmp_path / "files").iterdir()) == []


@pytest.mark.parametrize("key", ["../x", "a/b", "", "..", ".", "a\\b", "a\x00b", "/etc/passwd"])
async def test_keys_that_could_leave_the_root_are_rejected(
    storage: LocalFileStorage, key: str
) -> None:
    with pytest.raises(ValueError, match="Invalid storage key"):
        await storage.save(key, b"x")
    with pytest.raises(ValueError, match="Invalid storage key"):
        await storage.read(key)
    with pytest.raises(ValueError, match="Invalid storage key"):
        await storage.delete(key)
    with pytest.raises(ValueError, match="Invalid storage key"):
        await storage.exists(key)


async def test_reading_a_missing_key_raises(storage: LocalFileStorage) -> None:
    with pytest.raises(FileNotFoundError):
        await storage.read("missing.pdf")


async def test_dependency_builds_storage_from_settings(tmp_path: Path) -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/x", resume_storage_dir=tmp_path
    )

    storage = get_file_storage(settings)
    await storage.save("a.pdf", b"x")

    assert (tmp_path / "a.pdf").read_bytes() == b"x"
