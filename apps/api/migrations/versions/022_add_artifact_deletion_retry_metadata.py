"""Add deletion retry metadata columns to creator_artifacts.

Revision ID: 022
Revises: 021
Create Date: 2026-05-17 00:00:00.000000

Tracks failed storage deletions so a retry job can pick up and reattempt.
"""

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.add_column(
        "creator_artifacts",
        sa.Column("delete_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "creator_artifacts",
        sa.Column("delete_failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "creator_artifacts",
        sa.Column("delete_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "creator_artifacts",
        sa.Column(
            "delete_retry_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_creator_artifacts_pending_delete",
        "creator_artifacts",
        ["delete_failed_at"],
        postgresql_where=sa.text("delete_failed_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_creator_artifacts_pending_delete", "creator_artifacts")
    op.drop_column("creator_artifacts", "delete_retry_count")
    op.drop_column("creator_artifacts", "delete_error")
    op.drop_column("creator_artifacts", "delete_failed_at")
    op.drop_column("creator_artifacts", "delete_requested_at")
