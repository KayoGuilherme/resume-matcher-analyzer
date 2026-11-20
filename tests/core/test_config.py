from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/x")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://u:p@localhost:5432/x"
    assert settings.log_level == "DEBUG"
    assert settings.app_env == "local"


def test_missing_database_url_fails_naming_the_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "database_url" in str(exc_info.value).lower()


def test_settings_do_not_read_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql+asyncpg://from-file\n")

    with pytest.raises(ValidationError):
        Settings()


def test_resume_settings_have_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/x")
    monkeypatch.delenv("RESUME_MAX_UPLOAD_BYTES", raising=False)
    monkeypatch.delenv("RESUME_STORAGE_DIR", raising=False)

    settings = Settings()

    assert settings.resume_max_upload_bytes == 5 * 1024 * 1024
    assert settings.resume_storage_dir == Path("data/resumes")


def test_resume_settings_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/x")
    monkeypatch.setenv("RESUME_MAX_UPLOAD_BYTES", "1048576")
    monkeypatch.setenv("RESUME_STORAGE_DIR", "/data/resumes")

    settings = Settings()

    assert settings.resume_max_upload_bytes == 1_048_576
    assert settings.resume_storage_dir == Path("/data/resumes")


@pytest.mark.parametrize("value", ["0", "-5", "abc"])
def test_invalid_max_upload_size_fails_naming_the_setting(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/x")
    monkeypatch.setenv("RESUME_MAX_UPLOAD_BYTES", value)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "resume_max_upload_bytes" in str(exc_info.value).lower()


def test_env_example_lists_the_resume_settings() -> None:
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text()

    assert "RESUME_MAX_UPLOAD_BYTES=" in example
    assert "RESUME_STORAGE_DIR=" in example
