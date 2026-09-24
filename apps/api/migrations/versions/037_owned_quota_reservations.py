from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "037"
down_revision: str | None = "036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_quota_reservation_owners",
        sa.Column("owner_id", sa.String(255), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("operation_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.CheckConstraint("status IN ('reserved', 'consumed', 'cancelled')", name="ck_quota_owner_status"),
        sa.CheckConstraint(
            "operation_type IN ('llm', 'image_gen', 'tts', 'stt', 'render')",
            name="ck_quota_owner_operation",
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_quota_reservation_owners")
