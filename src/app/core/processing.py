"""Processing status, error codes and messages shared by resumes and jobs, defined once."""

from typing import Literal

from pydantic import BaseModel

from app.core.errors import DomainError

ProcessingStatus = Literal["uploaded", "processing", "ready", "failed"]


class ProcessingError(BaseModel):
    """Why the last processing run failed. Never contains resume or posting content."""

    code: str
    message: str


class AlreadyProcessingError(DomainError):
    status_code = 409
    code = "already_processing"


# Processing failures: stable code -> fixed message. Never built from exception text, which may
# carry document content or secrets.
PROCESSING_MESSAGES = {
    "llm_auth_failed": "The LLM provider rejected the credentials. Check LLM_API_KEY.",
    "llm_timeout": (
        "The LLM did not answer in time. Increase LLM_TIMEOUT_SECONDS or use a faster model."
    ),
    "llm_unavailable": (
        "The LLM provider was unavailable or rate limiting after several attempts. Try again later."
    ),
    "llm_invalid_output": (
        "The LLM's answer could not be validated against the expected schema. Try again or use a "
        "more capable model."
    ),
    "embedding_failed": (
        "Creating the embeddings failed. Check the EMBEDDING_* settings and that the embedding "
        "provider is reachable."
    ),
    "analysis_limit_exceeded": (
        "The analysis needs more LLM calls than allowed. Raise ANALYSIS_MAX_LLM_CALLS or "
        "ANALYSIS_MAX_REQUIREMENTS_PER_CALL, then try again."
    ),
    "embedding_model_mismatch": (
        "The resume and the job were embedded with different models. Process the older of the two "
        "again."
    ),
    "processing_interrupted": (
        "Processing was interrupted by an application restart. Process it again."
    ),
    "processing_failed": "Processing failed unexpectedly. Try again.",
}
