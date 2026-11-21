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
        "processing_interrupted",
        "processing_failed",
    }
    assert all(message and "\n" not in message for message in PROCESSING_MESSAGES.values())


def test_already_processing_is_a_409_with_its_code() -> None:
    error = AlreadyProcessingError("busy")

    assert (error.status_code, error.code, error.message) == (409, "already_processing", "busy")


def test_a_processing_error_has_a_code_and_a_message() -> None:
    assert ProcessingError(code="llm_timeout", message="m").model_dump() == {
        "code": "llm_timeout",
        "message": "m",
    }
