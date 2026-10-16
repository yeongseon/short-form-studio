from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "040"
down_revision: str | None = "039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_quota_reservation_attempts",
        sa.Column("status", sa.String(32), nullable=False, server_default="authorized"),
    )
    op.add_column(
        "workspace_quota_reservation_attempts",
        sa.Column("usage_event_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_quota_attempt_usage_event",
        "workspace_quota_reservation_attempts",
        "usage_events",
        ["usage_event_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_quota_attempt_status",
        "workspace_quota_reservation_attempts",
        "status IN ('authorized', 'accounted', 'unknown')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_quota_attempt_usage_event", "workspace_quota_reservation_attempts", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_quota_attempt_status", "workspace_quota_reservation_attempts", type_="check"
    )
    op.drop_column("workspace_quota_reservation_attempts", "usage_event_id")
    op.drop_column("workspace_quota_reservation_attempts", "status")
