"""Widen active_task_id from VARCHAR(255) to TEXT.

The column now stores a JSON array of Celery task IDs so it can exceed 255
characters when many concurrent scene-image tasks are tracked.

Revision ID: 010
Revises: 009
Create Date: 2025-01-01 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.alter_column(
        "creator_runs",
        "active_task_id",
        type_=sa.Text(),
        existing_type=sa.String(length=255),
    )

def downgrade() -> None:
    op.alter_column(
        "creator_runs",
        "active_task_id",
        type_=sa.String(length=255),
        existing_type=sa.Text(),
    )
