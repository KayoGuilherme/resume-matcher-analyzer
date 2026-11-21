"""Database models for job positions and their extracted requirements."""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'failed')", name="ck_job_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    requirements_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="uploaded")
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class JobRequirement(Base):
    """One requirement of a job with its vector.

    The vector size is set by migration 0005 from EMBEDDING_DIMENSION; the model leaves it open
    because settings cannot be read at import time.
    """

    __tablename__ = "job_requirements"
    __table_args__ = (
        UniqueConstraint("job_id", "position", name="uq_job_requirements_job_position"),
        CheckConstraint(
            "category IN ('skill', 'years', 'language', 'education', 'domain', 'soft')",
            name="ck_job_requirements_category",
        ),
        CheckConstraint(
            "priority IN ('must_have', 'nice_to_have')", name="ck_job_requirements_priority"
        ),
        Index(
            "ix_job_requirements_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("job.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text)
    priority_unclear: Mapped[bool] = mapped_column(Boolean)
    min_years: Mapped[float | None] = mapped_column(Float)
    keywords: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    source_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector())
    embedding_model: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
