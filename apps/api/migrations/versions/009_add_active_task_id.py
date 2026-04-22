"""Add active_task_id column to creator_runs.

Revision ID: 009
Revises: 008
Create Date: 2025-01-01 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.add_column(
        "creator_runs",
        sa.Column("active_task_id", sa.String(length=255), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("creator_runs", "active_task_id")
