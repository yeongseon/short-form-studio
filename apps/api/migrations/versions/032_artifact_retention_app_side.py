"""Move artifact retention computation from DDL to application.

Revision ID: 032
Revises: 031
Create Date: 2026-08-09 01:00:00.000000

Migration 031 baked ARTIFACT_RETENTION_DAYS into the DDL default, making the
schema non-deterministic (depends on environment at apply time). This breaks
reproducibility: two databases with the same schema version may have different
default expressions.

This migration reverts the DDL default to a constant 90 days. Retention is now
computed at INSERT time in application code (``packages/creator-service``),
which:

1. Makes the schema deterministic (same for all deployments)
2. Lets operators tune retention per-deployment without schema changes
3. Keeps all configuration in the runtime environment

The DDL default (90 days) serves as a fallback only. The application always
computes ``expires_at`` explicitly at INSERT, so the default is never used for
new rows created by the app. Existing rows created before this migration retain
their current ``expires_at`` values.

Companion changes:
- ``packages/creator-service/creator_service/postgres_render_storage.py``
- ``packages/creator-service/creator_service/postgres_audio_storage.py``
- ``packages/creator-service/creator_service/postgres_subtitle_storage.py``

All three files now compute ``expires_at`` from ARTIFACT_RETENTION_DAYS at
INSERT time.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "032"
down_revision: str | None = "031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Revert to a constant DDL default (same as 030).
    # Retention is now computed at INSERT time in application code.
    op.execute(
        "ALTER TABLE creator_artifacts "
        "ALTER COLUMN expires_at SET DEFAULT (NOW() + INTERVAL '90 days')"
    )


def downgrade() -> None:
    # This would restore the environment-dependent default from 031,
    # but doing so would require reading ARTIFACT_RETENTION_DAYS at downgrade time.
    # For safety, we just restore a constant 90-day default here.
    op.execute(
        "ALTER TABLE creator_artifacts "
        "ALTER COLUMN expires_at SET DEFAULT (NOW() + INTERVAL '90 days')"
    )
