"""Provider-agnostic embeddings. Business code imports from here and depends on
`EmbeddingClient`."""

from app.ai.embeddings.base import (
    EmbeddingAuthError,
    EmbeddingClient,
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingTimeoutError,
    EmbeddingTransientError,
)
from app.ai.embeddings.factory import get_embedding_client
from app.ai.embeddings.fake import FakeEmbeddingClient

__all__ = [
    "EmbeddingAuthError",
    "EmbeddingClient",
    "EmbeddingDimensionError",
    "EmbeddingError",
    "EmbeddingTimeoutError",
    "EmbeddingTransientError",
    "FakeEmbeddingClient",
    "get_embedding_client",
]
