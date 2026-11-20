"""create candidate profile

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_profile",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("target_role", sa.Text(), nullable=False),
        sa.Column("seniority", sa.Text(), nullable=False),
        sa.Column("total_years_coding", sa.Double(), nullable=False),
        sa.Column("stacks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("languages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notable_facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_candidate_profile_single_row"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("candidate_profile")
