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


_AI_VARIABLES = [
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_TEMPERATURE",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_API_KEY",
    "EMBEDDING_BASE_URL",
]


@pytest.fixture
def clean_ai_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/x")
    for name in _AI_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_ai_settings_defaults(clean_ai_env: pytest.MonkeyPatch) -> None:
    settings = Settings()

    assert settings.llm_provider is None
    assert settings.llm_model is None
    assert settings.llm_api_key is None
    assert settings.llm_base_url is None
    assert settings.llm_timeout_seconds == 120
    assert settings.llm_temperature == 0
    assert settings.embedding_provider == "openai_compatible"
    assert settings.embedding_model == "bge-m3"
    assert settings.embedding_dimension == 1024
    assert settings.embedding_api_key is None
    assert settings.embedding_base_url is None


def test_ai_settings_can_be_overridden(clean_ai_env: pytest.MonkeyPatch) -> None:
    clean_ai_env.setenv("LLM_PROVIDER", "openai_compatible")
    clean_ai_env.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    clean_ai_env.setenv("LLM_MODEL", "llama3.1")
    clean_ai_env.setenv("LLM_TIMEOUT_SECONDS", "30.5")
    clean_ai_env.setenv("LLM_TEMPERATURE", "0.3")
    clean_ai_env.setenv("EMBEDDING_PROVIDER", "openai")
    clean_ai_env.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
    clean_ai_env.setenv("EMBEDDING_DIMENSION", "1536")
    clean_ai_env.setenv("EMBEDDING_API_KEY", "placeholder")

    settings = Settings()

    assert settings.llm_provider == "openai_compatible"
    assert settings.llm_model == "llama3.1"
    assert settings.llm_timeout_seconds == 30.5
    assert settings.llm_temperature == 0.3
    assert settings.embedding_provider == "openai"
    assert settings.embedding_dimension == 1536
    assert settings.embedding_api_key is not None
    assert settings.embedding_api_key.get_secret_value() == "placeholder"


@pytest.mark.parametrize("name", ["LLM_PROVIDER", "EMBEDDING_PROVIDER"])
def test_unknown_provider_fails_naming_the_setting(
    clean_ai_env: pytest.MonkeyPatch, name: str
) -> None:
    clean_ai_env.setenv(name, "gemini")

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert name.lower() in str(exc_info.value).lower()


@pytest.mark.parametrize("value", ["0", "abc"])
def test_invalid_llm_timeout_fails_naming_the_setting(
    clean_ai_env: pytest.MonkeyPatch, value: str
) -> None:
    clean_ai_env.setenv("LLM_TIMEOUT_SECONDS", value)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "llm_timeout_seconds" in str(exc_info.value).lower()


@pytest.mark.parametrize("value", ["0", "2001", "abc"])
def test_invalid_embedding_dimension_fails_naming_the_setting(
    clean_ai_env: pytest.MonkeyPatch, value: str
) -> None:
    clean_ai_env.setenv("EMBEDDING_DIMENSION", value)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "embedding_dimension" in str(exc_info.value).lower()


def test_empty_temperature_means_none(clean_ai_env: pytest.MonkeyPatch) -> None:
    clean_ai_env.setenv("LLM_TEMPERATURE", "")

    assert Settings().llm_temperature is None


def test_empty_optional_values_mean_unset(clean_ai_env: pytest.MonkeyPatch) -> None:
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "EMBEDDING_API_KEY"):
        clean_ai_env.setenv(name, "")

    settings = Settings()

    assert settings.llm_provider is None
    assert settings.llm_api_key is None
    assert settings.embedding_api_key is None


def test_settings_are_valid_with_only_the_database_url(clean_ai_env: pytest.MonkeyPatch) -> None:
    assert Settings().database_url.startswith("postgresql")


def test_validation_error_does_not_echo_the_api_key(clean_ai_env: pytest.MonkeyPatch) -> None:
    clean_ai_env.setenv("LLM_API_KEY", "sk-super-secret-value")
    clean_ai_env.setenv("LLM_TIMEOUT_SECONDS", "abc")

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "sk-super-secret-value" not in str(exc_info.value)


def test_api_key_is_not_shown_in_repr(clean_ai_env: pytest.MonkeyPatch) -> None:
    clean_ai_env.setenv("LLM_API_KEY", "sk-super-secret-value")

    assert "sk-super-secret-value" not in repr(Settings())


def test_env_example_lists_every_ai_setting_without_real_secrets() -> None:
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text()

    for name in _AI_VARIABLES:
        assert f"\n{name}=" in example
    assert "sk-" not in example
    assert "Anthropic" in example and "OpenAI" in example and "Ollama" in example
