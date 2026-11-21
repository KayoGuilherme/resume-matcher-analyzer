import pytest

from app.ai.embeddings.base import (
    EmbeddingAuthError,
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingTimeoutError,
    EmbeddingTransientError,
)
from app.ai.error_codes import processing_error_code
from app.ai.llm.base import (
    LLMAuthError,
    LLMError,
    LLMInvalidOutputError,
    LLMTimeoutError,
    LLMTransientError,
)
from app.ai.matching.errors import (
    AnalysisInvariantError,
    AnalysisLimitError,
    EmbeddingModelMismatchError,
    JudgeIncompleteError,
)
from app.core.processing import PROCESSING_MESSAGES, AlreadyProcessingError, ProcessingError


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (LLMAuthError("x"), "llm_auth_failed"),
        (LLMTimeoutError("x"), "llm_timeout"),
        (LLMTransientError("x"), "llm_unavailable"),
        (LLMInvalidOutputError("x"), "llm_invalid_output"),
        (EmbeddingError("x"), "embedding_failed"),
        (EmbeddingAuthError("x"), "embedding_failed"),
        (EmbeddingTimeoutError("x"), "embedding_failed"),
        (EmbeddingTransientError("x"), "embedding_failed"),
        (EmbeddingDimensionError(1024, 768), "embedding_failed"),
        (AnalysisLimitError("x"), "analysis_limit_exceeded"),
        (EmbeddingModelMismatchError("x"), "embedding_model_mismatch"),
        (JudgeIncompleteError("x"), "llm_invalid_output"),
        (AnalysisInvariantError("x"), "processing_failed"),
        (LLMError("other rejection"), "processing_failed"),
        (RuntimeError("boom"), "processing_failed"),
    ],
)
def test_every_error_family_maps_to_its_code(error: Exception, code: str) -> None:
    assert processing_error_code(error) == code


def test_every_code_has_one_fixed_message() -> None:
    assert set(PROCESSING_MESSAGES) == {
        "llm_auth_failed",
        "llm_timeout",
        "llm_unavailable",
        "llm_invalid_output",
        "embedding_failed",
        "analysis_limit_exceeded",
        "embedding_model_mismatch",
        "processing_interrupted",
        "processing_failed",
    }
    assert all(message and "\n" not in message for message in PROCESSING_MESSAGES.values())
    assert not any(c in message for message in PROCESSING_MESSAGES.values() for c in "{}%")


def test_the_limit_message_names_both_settings() -> None:
    message = PROCESSING_MESSAGES["analysis_limit_exceeded"]

    assert "ANALYSIS_MAX_LLM_CALLS" in message
    assert "ANALYSIS_MAX_REQUIREMENTS_PER_CALL" in message


def test_matching_does_not_import_the_error_code_mapping() -> None:
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "src" / "app" / "ai" / "matching"
    assert not any("error_codes" in path.read_text() for path in source.rglob("*.py"))


def test_already_processing_is_a_409_with_its_code() -> None:
    error = AlreadyProcessingError("busy")

    assert (error.status_code, error.code, error.message) == (409, "already_processing", "busy")


def test_a_processing_error_has_a_code_and_a_message() -> None:
    assert ProcessingError(code="llm_timeout", message="m").model_dump() == {
        "code": "llm_timeout",
        "message": "m",
    }
