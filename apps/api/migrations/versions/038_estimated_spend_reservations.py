from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "038"
down_revision: str | None = "037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_quota_reservations",
        sa.Column("reserved_estimated_cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
    )
    op.add_column(
        "workspace_quota_reservation_owners",
        sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
    )
    op.add_column(
        "workspace_quota_reservation_owners",
        sa.Column("settled_estimated_cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
    )
    op.drop_constraint("ck_quota_owner_status", "workspace_quota_reservation_owners", type_="check")
    op.create_check_constraint(
        "ck_quota_owner_status",
        "workspace_quota_reservation_owners",
        "status IN ('reserved', 'consumed', 'settled', 'cancelled', 'billable_unknown')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_quota_owner_status", "workspace_quota_reservation_owners", type_="check")
    op.create_check_constraint(
        "ck_quota_owner_status",
        "workspace_quota_reservation_owners",
        "status IN ('reserved', 'consumed', 'cancelled')",
    )
    op.drop_column("workspace_quota_reservation_owners", "settled_estimated_cost_usd")
    op.drop_column("workspace_quota_reservation_owners", "estimated_cost_usd")
    op.drop_column("workspace_quota_reservations", "reserved_estimated_cost_usd")
