"""Create usage tracking and workspace quota tables.

Revision ID: 016
Revises: 011
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_key", sa.String(length=100), nullable=False),
        sa.Column("operation_type", sa.String(length=50), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("image_count", sa.Integer(), nullable=True),
        sa.Column("audio_seconds", sa.Numeric(10, 2), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("cost_config_version", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_check_constraint(
        "ck_usage_events_operation_type",
        "usage_events",
        "operation_type IN ('llm', 'image_gen', 'tts', 'stt', 'render')",
    )
    op.create_index("ix_usage_workspace", "usage_events", ["workspace_id", "created_at"])
    op.create_index("ix_usage_run", "usage_events", ["run_id"])

    op.create_table(
        "workspace_quotas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("monthly_llm_calls", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column(
            "monthly_image_generations",
            sa.Integer(),
            nullable=False,
            server_default="200",
        ),
        sa.Column("monthly_tts_requests", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column(
            "monthly_cost_usd",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="50.00",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_quotas")
    op.drop_index("ix_usage_run", table_name="usage_events")
    op.drop_index("ix_usage_workspace", table_name="usage_events")
    op.drop_constraint("ck_usage_events_operation_type", "usage_events")
    op.drop_table("usage_events")
