"""Create creator_stage_reviews table.

Revision ID: 003
Revises: 002
Create Date: 2025-01-01 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "creator_stage_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("creator_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_name", sa.String(length=50), nullable=False),
        sa.Column("review_status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("reviewer", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # CHECK constraint for review_status
    op.create_check_constraint(
        "ck_creator_stage_reviews_review_status",
        "creator_stage_reviews",
        "review_status IN ('pending', 'approved', 'rejected', 'skipped')",
    )

    # Composite index for lookups by run + stage
    op.create_index(
        "ix_creator_stage_reviews_run_stage",
        "creator_stage_reviews",
        ["run_id", "stage_name"],
    )

def downgrade() -> None:
    op.drop_index("ix_creator_stage_reviews_run_stage")
    op.drop_constraint("ck_creator_stage_reviews_review_status", "creator_stage_reviews")
    op.drop_table("creator_stage_reviews")
