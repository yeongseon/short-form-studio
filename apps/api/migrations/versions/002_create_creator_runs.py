"""Create creator_runs table.

Revision ID: 002
Revises: 001
Create Date: 2025-01-01 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "creator_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("creator_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("current_stage", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("review_stage", sa.String(length=50), nullable=True),
        sa.Column("restart_from", sa.String(length=50), nullable=True),
        sa.Column("model_defaults_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("style_preset", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # CHECK constraint for status
    op.create_check_constraint(
        "ck_creator_runs_status",
        "creator_runs",
        "status IN ('pending', 'running', 'paused', 'completed', 'failed', 'cancelled')",
    )

    # Index on project_id for FK lookups
    op.create_index("ix_creator_runs_project_id", "creator_runs", ["project_id"])

    # Reuse the update_updated_at_column() function from migration 001
    op.execute(
        """
    CREATE TRIGGER set_updated_at_creator_runs
    BEFORE UPDATE ON creator_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
    """
    )

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_creator_runs ON creator_runs")
    op.drop_constraint("ck_creator_runs_status", "creator_runs")
    op.drop_index("ix_creator_runs_project_id")
    op.drop_table("creator_runs")
