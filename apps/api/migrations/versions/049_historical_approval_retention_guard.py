from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "049"
down_revision: str | None = "048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_resolved_timeline_approvals",
        sa.Column(
            "review_id", sa.Integer(),
            sa.ForeignKey("creator_stage_reviews.id", ondelete="CASCADE"), primary_key=True,
        ),
    )
    op.create_table(
        "creator_media_retention_unresolved_workspaces",
        sa.Column(
            "workspace_id", sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute(
        """DO $backfill$
            DECLARE
                approved_review record;
                approved_timeline record;
                parsed_notes jsonb;
                parsed_revision integer;
                parsed_timeline_id text;
            BEGIN
                FOR approved_review IN
                    SELECT review.id, review.notes, run.project_id, run.workspace_id
                    FROM creator_stage_reviews review
                    JOIN creator_runs run ON run.id = review.run_id
                    WHERE review.stage_name = 'TIMELINE_REVIEW'
                      AND review.review_status = 'approved'
                LOOP
                    BEGIN
                        parsed_notes := approved_review.notes::jsonb;
                        parsed_timeline_id := parsed_notes->>'timeline_id';
                        parsed_revision := (parsed_notes->>'revision')::integer;
                    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
                        CONTINUE;
                    END;
                    SELECT timeline.timeline_id, timeline.revision, timeline.segments_json
                    INTO approved_timeline
                    FROM creator_timelines timeline
                    WHERE timeline.project_id = approved_review.project_id
                      AND timeline.workspace_id = approved_review.workspace_id
                      AND timeline.timeline_id = parsed_timeline_id
                      AND timeline.revision = parsed_revision;
                    IF FOUND THEN
                        INSERT INTO creator_approved_timeline_assets (
                            review_id, workspace_id, timeline_id, revision, asset_id
                        )
                        SELECT DISTINCT approved_review.id, approved_review.workspace_id,
                            approved_timeline.timeline_id, approved_timeline.revision,
                            (segment->>'asset_id')::bigint
                        FROM jsonb_array_elements(approved_timeline.segments_json::jsonb) segment
                        WHERE jsonb_typeof(segment->'asset_id') = 'number'
                        ON CONFLICT DO NOTHING;
                        INSERT INTO creator_resolved_timeline_approvals (review_id)
                        VALUES (approved_review.id) ON CONFLICT DO NOTHING;
                    END IF;
                END LOOP;
            END $backfill$"""
    )
    op.execute(
        """INSERT INTO creator_media_retention_unresolved_workspaces (workspace_id)
            SELECT DISTINCT run.workspace_id
            FROM creator_stage_reviews review
            JOIN creator_runs run ON run.id = review.run_id
            WHERE review.stage_name = 'TIMELINE_REVIEW'
              AND review.review_status = 'approved'
              AND NOT EXISTS (
                  SELECT 1 FROM creator_resolved_timeline_approvals resolved
                  WHERE resolved.review_id = review.id
              )
            ON CONFLICT DO NOTHING"""
    )


def downgrade() -> None:
    op.drop_table("creator_media_retention_unresolved_workspaces")
    op.drop_table("creator_resolved_timeline_approvals")
