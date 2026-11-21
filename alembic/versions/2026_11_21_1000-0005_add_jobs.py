"""add job positions and their requirements

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-21

The size of the `job_requirements.embedding` column is the EMBEDDING_DIMENSION in the environment
when this migration is applied; it must equal the size of `resume_chunk.embedding`. To change it
later, write a new migration (see the README, "Changing the embedding model"); never edit this one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config import get_settings

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dimension = get_settings().embedding_dimension
    op.create_table(
        "job",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("requirements_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), server_default="uploaded", nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("extraction", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'failed')", name="ck_job_status"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "job_requirements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("priority_unclear", sa.Boolean(), nullable=False),
        sa.Column("min_years", sa.Float(), nullable=True),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(dimension), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "category IN ('skill', 'years', 'language', 'education', 'domain', 'soft')",
            name="ck_job_requirements_category",
        ),
        sa.CheckConstraint(
            "priority IN ('must_have', 'nice_to_have')", name="ck_job_requirements_priority"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "position", name="uq_job_requirements_job_position"),
    )
    op.create_index("ix_job_requirements_job_id", "job_requirements", ["job_id"])
    op.execute(
        "CREATE INDEX ix_job_requirements_embedding ON job_requirements "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("job_requirements")
    op.drop_table("job")
