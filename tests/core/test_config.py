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
