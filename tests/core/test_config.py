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

_ANALYSIS_VARIABLES = [
    "ANALYSIS_TOP_K",
    "ANALYSIS_MIN_SIMILARITY",
    "ANALYSIS_MAX_REQUIREMENTS_PER_CALL",
    "ANALYSIS_MAX_LLM_CALLS",
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


@pytest.fixture
def clean_analysis_env(clean_ai_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in _ANALYSIS_VARIABLES:
        clean_ai_env.delenv(name, raising=False)
    return clean_ai_env


def test_analysis_settings_defaults(clean_analysis_env: pytest.MonkeyPatch) -> None:
    settings = Settings()

    assert settings.analysis_top_k == 5
    assert settings.analysis_min_similarity == 0.4
    assert settings.analysis_max_requirements_per_call == 8
    assert settings.analysis_max_llm_calls == 10


def test_analysis_settings_can_be_overridden(clean_analysis_env: pytest.MonkeyPatch) -> None:
    clean_analysis_env.setenv("ANALYSIS_TOP_K", "3")
    clean_analysis_env.setenv("ANALYSIS_MIN_SIMILARITY", "0.55")
    clean_analysis_env.setenv("ANALYSIS_MAX_REQUIREMENTS_PER_CALL", "4")
    clean_analysis_env.setenv("ANALYSIS_MAX_LLM_CALLS", "2")

    settings = Settings()

    assert settings.analysis_top_k == 3
    assert settings.analysis_min_similarity == 0.55
    assert settings.analysis_max_requirements_per_call == 4
    assert settings.analysis_max_llm_calls == 2


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ANALYSIS_MIN_SIMILARITY", "0"),
        ("ANALYSIS_MIN_SIMILARITY", "1"),
        ("ANALYSIS_TOP_K", "1"),
        ("ANALYSIS_TOP_K", "20"),
        ("ANALYSIS_MAX_REQUIREMENTS_PER_CALL", "50"),
        ("ANALYSIS_MAX_LLM_CALLS", "100"),
    ],
)
def test_analysis_boundaries_are_accepted(
    clean_analysis_env: pytest.MonkeyPatch, name: str, value: str
) -> None:
    clean_analysis_env.setenv(name, value)

    Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ANALYSIS_MIN_SIMILARITY", "1.5"),
        ("ANALYSIS_MIN_SIMILARITY", "-0.1"),
        ("ANALYSIS_MIN_SIMILARITY", "nan"),
        ("ANALYSIS_MIN_SIMILARITY", "abc"),
        ("ANALYSIS_TOP_K", "0"),
        ("ANALYSIS_TOP_K", "21"),
        ("ANALYSIS_MAX_REQUIREMENTS_PER_CALL", "0"),
        ("ANALYSIS_MAX_REQUIREMENTS_PER_CALL", "51"),
        ("ANALYSIS_MAX_LLM_CALLS", "0"),
        ("ANALYSIS_MAX_LLM_CALLS", "101"),
        ("ANALYSIS_MAX_LLM_CALLS", "many"),
    ],
)
def test_invalid_analysis_setting_fails_naming_the_setting(
    clean_analysis_env: pytest.MonkeyPatch, name: str, value: str
) -> None:
    clean_analysis_env.setenv(name, value)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert name.lower() in str(exc_info.value).lower()


def test_env_example_lists_the_analysis_settings_with_their_defaults() -> None:
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text()

    assert "\nANALYSIS_TOP_K=5\n" in example
    assert "\nANALYSIS_MIN_SIMILARITY=0.4\n" in example
    assert "\nANALYSIS_MAX_REQUIREMENTS_PER_CALL=8\n" in example
    assert "\nANALYSIS_MAX_LLM_CALLS=10\n" in example
    assert "depends on the embedding model" in example


_REPORT_VARIABLES = [
    "SCORE_WEIGHT_MUST_HAVE",
    "SCORE_WEIGHT_NICE_TO_HAVE",
    "SCORE_WEIGHT_KEYWORDS",
    "SCORE_PARTIAL_CREDIT",
    "SCORE_PENALTY_CRITICAL",
    "SCORE_PENALTY_WARNING",
    "SCORE_PENALTY_INFO",
    "SCORE_PASS_THRESHOLD",
    "SCORE_BORDERLINE_THRESHOLD",
    "SCREENER_RUNS",
    "REPORT_MAX_SUGGESTIONS",
]


@pytest.fixture
def clean_report_env(clean_ai_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in _REPORT_VARIABLES:
        clean_ai_env.delenv(name, raising=False)
    return clean_ai_env


def test_report_settings_defaults(clean_report_env: pytest.MonkeyPatch) -> None:
    settings = Settings()

    assert settings.score_weight_must_have == 0.6
    assert settings.score_weight_nice_to_have == 0.15
    assert settings.score_weight_keywords == 0.25
    assert settings.score_partial_credit == 0.5
    assert settings.score_penalty_critical == 40
    assert settings.score_penalty_warning == 5
    assert settings.score_penalty_info == 1
    assert settings.score_pass_threshold == 70
    assert settings.score_borderline_threshold == 50
    assert settings.screener_runs == 3
    assert settings.report_max_suggestions == 8


def test_report_settings_can_be_overridden(clean_report_env: pytest.MonkeyPatch) -> None:
    clean_report_env.setenv("SCORE_PASS_THRESHOLD", "80")
    clean_report_env.setenv("SCREENER_RUNS", "5")
    clean_report_env.setenv("REPORT_MAX_SUGGESTIONS", "0")

    settings = Settings()

    assert settings.score_pass_threshold == 80
    assert settings.screener_runs == 5
    assert settings.report_max_suggestions == 0


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SCREENER_RUNS", "1"),
        ("SCREENER_RUNS", "10"),
        ("REPORT_MAX_SUGGESTIONS", "0"),
        ("REPORT_MAX_SUGGESTIONS", "30"),
        ("SCORE_PARTIAL_CREDIT", "0"),
        ("SCORE_PARTIAL_CREDIT", "1"),
        ("SCORE_PENALTY_CRITICAL", "100"),
        ("SCORE_WEIGHT_NICE_TO_HAVE", "0"),
    ],
)
def test_report_boundaries_are_accepted(
    clean_report_env: pytest.MonkeyPatch, name: str, value: str
) -> None:
    clean_report_env.setenv(name, value)

    Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SCREENER_RUNS", "0"),
        ("SCREENER_RUNS", "11"),
        ("SCREENER_RUNS", "often"),
        ("REPORT_MAX_SUGGESTIONS", "-1"),
        ("REPORT_MAX_SUGGESTIONS", "31"),
        ("SCORE_PARTIAL_CREDIT", "1.5"),
        ("SCORE_WEIGHT_KEYWORDS", "heavy"),
        ("SCORE_WEIGHT_MUST_HAVE", "nan"),
        ("SCORE_WEIGHT_NICE_TO_HAVE", "-0.1"),
        ("SCORE_PENALTY_WARNING", "101"),
        ("SCORE_PASS_THRESHOLD", "101"),
        ("SCORE_BORDERLINE_THRESHOLD", "-1"),
    ],
)
def test_invalid_report_setting_fails_naming_the_setting(
    clean_report_env: pytest.MonkeyPatch, name: str, value: str
) -> None:
    clean_report_env.setenv(name, value)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert name.lower() in str(exc_info.value).lower()


def test_all_weights_zero_fails_naming_the_weights(
    clean_report_env: pytest.MonkeyPatch,
) -> None:
    for name in ("SCORE_WEIGHT_MUST_HAVE", "SCORE_WEIGHT_NICE_TO_HAVE", "SCORE_WEIGHT_KEYWORDS"):
        clean_report_env.setenv(name, "0")

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    message = str(exc_info.value)
    assert "SCORE_WEIGHT_MUST_HAVE" in message and "SCORE_WEIGHT_KEYWORDS" in message


@pytest.mark.parametrize(("borderline", "pass_"), [("80", "70"), ("70", "70")])
def test_thresholds_in_the_wrong_order_fail_naming_the_borderline(
    clean_report_env: pytest.MonkeyPatch, borderline: str, pass_: str
) -> None:
    clean_report_env.setenv("SCORE_BORDERLINE_THRESHOLD", borderline)
    clean_report_env.setenv("SCORE_PASS_THRESHOLD", pass_)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "SCORE_BORDERLINE_THRESHOLD" in str(exc_info.value)


def test_env_example_lists_the_report_settings_with_their_defaults() -> None:
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    defaults = {
        "SCORE_WEIGHT_MUST_HAVE": "0.6",
        "SCORE_WEIGHT_NICE_TO_HAVE": "0.15",
        "SCORE_WEIGHT_KEYWORDS": "0.25",
        "SCORE_PARTIAL_CREDIT": "0.5",
        "SCORE_PENALTY_CRITICAL": "40",
        "SCORE_PENALTY_WARNING": "5",
        "SCORE_PENALTY_INFO": "1",
        "SCORE_PASS_THRESHOLD": "70",
        "SCORE_BORDERLINE_THRESHOLD": "50",
        "SCREENER_RUNS": "3",
        "REPORT_MAX_SUGGESTIONS": "8",
    }

    assert set(defaults) == set(_REPORT_VARIABLES)
    for name, value in defaults.items():
        assert f"\n{name}={value}\n" in example
    assert "relative" in example and "0-100" in example
