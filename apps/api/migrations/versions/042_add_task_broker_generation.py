from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "042"
down_revision: str | None = "041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "creator_run_tasks",
        sa.Column("broker_generation", sa.String(length=255), nullable=True),
    )
    op.execute(
        """UPDATE creator_run_tasks
           SET broker_generation = (
               SELECT epoch FROM creator_broker_state WHERE singleton = TRUE
           )
           WHERE status IN ('pending', 'queued', 'running')"""
    )
    op.create_index(
        "ix_run_tasks_broker_generation_active",
        "creator_run_tasks",
        ["broker_generation"],
        postgresql_where=sa.text("status IN ('pending', 'queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_run_tasks_broker_generation_active", table_name="creator_run_tasks"
    )
    op.drop_column("creator_run_tasks", "broker_generation")
