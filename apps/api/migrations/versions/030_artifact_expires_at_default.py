"""Set default expiry on creator_artifacts.expires_at.

Revision ID: 030
Revises: 029
Create Date: 2026-07-23 00:00:00.000000

Migration 024 created ``creator_artifacts.expires_at`` as nullable with no
default. This means the column is always NULL unless explicitly set, so the
expiry enforcement in ``creator_artifact_download.py:51-55`` is dead code.

This migration adds a server-side default of 90 days from creation:

    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '90 days')

New rows get the default automatically (no app code change needed).
Existing rows stay NULL (never expires) — correct backfill behavior.

To disable expiry for specific artifacts (e.g. published/keep-forever),
set ``expires_at = NULL`` explicitly or update to a far-future date.

See ``apps/api/src/shorts_api/routes/creator_artifact_download.py:51-55``
for the enforcement check, and
``apps/worker-orchestrator/tasks/retry_failed_artifact_deletions.py``
for the periodic cleanup that retries failed deletions (every 5 minutes).
Migration 031 makes the retention window configurable via
``ARTIFACT_RETENTION_DAYS`` and adds a ``sweep_expired_artifacts`` beat
task (every 10 minutes) that marks expired rows for deletion.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "030"
down_revision: str | None = "029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add server-side default: 90 days from creation.
    # New INSERTs that don't specify expires_at will get this value.
    op.execute(
        "ALTER TABLE creator_artifacts "
        "ALTER COLUMN expires_at SET DEFAULT (NOW() + INTERVAL '90 days')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE creator_artifacts ALTER COLUMN expires_at DROP DEFAULT")
