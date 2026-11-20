"""Database model for stored resumes (one row per distinct file content)."""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Resume(Base):
    __tablename__ = "resume"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_resume_sha256"),
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'failed')", name="ck_resume_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))
    original_filename: Mapped[str] = mapped_column(Text)
    file_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    parsing_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="uploaded")
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ResumeChunk(Base):
    """One bullet or skills line of a resume with its vector.

    The vector size is set by migration 0004 from EMBEDDING_DIMENSION; the model leaves it open
    because settings cannot be read at import time.
    """

    __tablename__ = "resume_chunk"
    __table_args__ = (
        CheckConstraint(
            "section IN ('experience', 'projects', 'skills')", name="ck_resume_chunk_section"
        ),
        Index(
            "ix_resume_chunk_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    resume_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("resume.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(Text)
    experience_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector())
    embedding_model: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
