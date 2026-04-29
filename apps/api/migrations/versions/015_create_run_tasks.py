"""Create creator_run_tasks table.

Revision ID: 015
Revises: 011
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_run_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("creator_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_check_constraint(
        "ck_creator_run_tasks_status",
        "creator_run_tasks",
        "status IN ('queued', 'pending', 'running', 'success', 'failed', 'revoked', 'rejected')",
    )

    op.create_index("ix_run_tasks_run_id", "creator_run_tasks", ["run_id"])
    op.execute(
        """
    CREATE INDEX ix_run_tasks_active_status
    ON creator_run_tasks (status)
    WHERE status IN ('pending', 'running');
    """
    )
    op.create_index("ix_run_tasks_celery_id", "creator_run_tasks", ["celery_task_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_run_tasks_celery_id", "creator_run_tasks")
    op.drop_index("ix_run_tasks_active_status", "creator_run_tasks")
    op.drop_index("ix_run_tasks_run_id", "creator_run_tasks")
    op.drop_constraint("ck_creator_run_tasks_status", "creator_run_tasks")
    op.drop_table("creator_run_tasks")
