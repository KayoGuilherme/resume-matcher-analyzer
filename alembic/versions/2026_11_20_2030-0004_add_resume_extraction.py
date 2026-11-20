"""add resume processing status, extraction and chunks

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-20

The size of the `embedding` column is the EMBEDDING_DIMENSION in the environment when this
migration is applied. To change it later, write a new migration (see the README, "Changing the
embedding model"); never edit this one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config import get_settings

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dimension = get_settings().embedding_dimension
    op.add_column(
        "resume", sa.Column("status", sa.Text(), server_default="uploaded", nullable=False)
    )
    op.add_column("resume", sa.Column("error_code", sa.Text(), nullable=True))
    op.add_column("resume", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column(
        "resume", sa.Column("extraction", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.create_check_constraint(
        "ck_resume_status", "resume", "status IN ('uploaded', 'processing', 'ready', 'failed')"
    )

    op.create_table(
        "resume_chunk",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("experience_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(dimension), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "section IN ('experience', 'projects', 'skills')", name="ck_resume_chunk_section"
        ),
        sa.ForeignKeyConstraint(["resume_id"], ["resume.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resume_chunk_resume_id", "resume_chunk", ["resume_id"])
    op.execute(
        "CREATE INDEX ix_resume_chunk_embedding ON resume_chunk "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("resume_chunk")
    op.drop_constraint("ck_resume_status", "resume", type_="check")
    op.drop_column("resume", "extraction")
    op.drop_column("resume", "error_message")
    op.drop_column("resume", "error_code")
    op.drop_column("resume", "status")
