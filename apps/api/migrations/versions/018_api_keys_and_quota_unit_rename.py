from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    with op.batch_alter_table("workspace_quotas") as batch_op:
        batch_op.alter_column(
            "monthly_tts_seconds",
            new_column_name="monthly_tts_requests",
            existing_type=sa.Integer(),
            existing_nullable=False,
            existing_server_default=sa.text("'3600'::integer"),
        )

    with op.batch_alter_table("workspace_quota_reservations") as batch_op:
        batch_op.alter_column(
            "tts_count",
            new_column_name="tts_request_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
            existing_server_default=sa.text("'0'::integer"),
        )


def downgrade() -> None:
    with op.batch_alter_table("workspace_quota_reservations") as batch_op:
        batch_op.alter_column(
            "tts_request_count",
            new_column_name="tts_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
            existing_server_default=sa.text("'0'::integer"),
        )

    with op.batch_alter_table("workspace_quotas") as batch_op:
        batch_op.alter_column(
            "monthly_tts_requests",
            new_column_name="monthly_tts_seconds",
            existing_type=sa.Integer(),
            existing_nullable=False,
            existing_server_default=sa.text("'3600'::integer"),
        )

    op.drop_table("api_keys")
