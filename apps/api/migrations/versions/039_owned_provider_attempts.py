from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "039"
down_revision: str | None = "038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_quota_reservation_attempts",
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("attempt_id", sa.String(255), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["workspace_quota_reservation_owners.owner_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("owner_id", "attempt_id"),
        sa.CheckConstraint("estimated_cost_usd > 0", name="ck_quota_attempt_positive_cost"),
    )


def downgrade() -> None:
    op.drop_table("workspace_quota_reservation_attempts")
