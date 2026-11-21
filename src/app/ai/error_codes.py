"""Maps AI-layer errors to the stable processing error codes (see `core/processing.py`)."""

from app.ai.embeddings.base import EmbeddingError
from app.ai.llm.base import (
    LLMAuthError,
    LLMInvalidOutputError,
    LLMTimeoutError,
    LLMTransientError,
)
from app.ai.matching.errors import (
    AnalysisLimitError,
    EmbeddingModelMismatchError,
    JudgeIncompleteError,
)


def processing_error_code(error: Exception) -> str:
    """The one place where AI-layer errors become processing error codes."""
    if isinstance(error, LLMAuthError):
        return "llm_auth_failed"
    if isinstance(error, LLMTimeoutError):
        return "llm_timeout"
    if isinstance(error, LLMTransientError):
        return "llm_unavailable"
    if isinstance(error, LLMInvalidOutputError):
        return "llm_invalid_output"
    if isinstance(error, EmbeddingError):
        return "embedding_failed"
    if isinstance(error, AnalysisLimitError):
        return "analysis_limit_exceeded"
    if isinstance(error, EmbeddingModelMismatchError):
        return "embedding_model_mismatch"
    if isinstance(error, JudgeIncompleteError):
        return "llm_invalid_output"
    return "processing_failed"
