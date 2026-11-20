"""Database model for the single candidate profile."""

from typing import Any

from sqlalchemy import CheckConstraint, Double, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

PROFILE_ID = 1


class CandidateProfile(Base):
    """The one candidate profile. The fixed key makes "exactly one row" a database rule."""

    __tablename__ = "candidate_profile"
    __table_args__ = (
        CheckConstraint(f"id = {PROFILE_ID}", name="ck_candidate_profile_single_row"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    target_role: Mapped[str] = mapped_column(Text)
    seniority: Mapped[str] = mapped_column(Text)
    total_years_coding: Mapped[float] = mapped_column(Double)
    stacks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    languages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    notable_facts: Mapped[list[str]] = mapped_column(JSONB)
