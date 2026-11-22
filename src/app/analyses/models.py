"""Database model for gap analyses: one row per resume + job + inputs, holding the whole result."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Analysis(Base):
    __tablename__ = "analysis"
    __table_args__ = (
        CheckConstraint("status IN ('processing', 'ready', 'failed')", name="ck_analysis_status"),
        # One active analysis per inputs: a database rule, so two simultaneous requests share one.
        Index(
            "uq_analysis_cache_key_active",
            "cache_key",
            unique=True,
            postgresql_where=text("status IN ('processing', 'ready')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    resume_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("resume.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("job.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    cache_key: Mapped[str] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
