"""Errors shared by the AI layers."""

from app.core.errors import DomainError


class AINotConfiguredError(DomainError):
    """The LLM or the embeddings are not usable. Names the missing setting, never a value."""

    status_code = 503
    code = "ai_not_configured"
