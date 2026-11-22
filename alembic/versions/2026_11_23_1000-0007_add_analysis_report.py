"""add the screening report to analyses

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-23

The part of the report that costs tokens or depends on rows that can change later (the simulated
screener, the rewrite suggestions, the missing keywords and a snapshot of the resume's parsing
issues), stored as JSON next to the result. Nullable: analyses made before reports existed have
none. The score, the actions and the Markdown are computed when the report is read.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis", sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("analysis", "report")
