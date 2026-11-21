"""add gap analyses

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-22

One row per analysis of a resume against a job, with its status, the cache key that identifies its
inputs and the whole result as JSON. The partial unique index allows only one `processing` or
`ready` analysis per cache key (a `failed` one does not block a new run).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('processing', 'ready', 'failed')", name="ck_analysis_status"),
        sa.ForeignKeyConstraint(["resume_id"], ["resume.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_resume_id", "analysis", ["resume_id"])
    op.create_index("ix_analysis_job_id", "analysis", ["job_id"])
    op.create_index(
        "uq_analysis_cache_key_active",
        "analysis",
        ["cache_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('processing', 'ready')"),
    )


def downgrade() -> None:
    op.drop_table("analysis")
