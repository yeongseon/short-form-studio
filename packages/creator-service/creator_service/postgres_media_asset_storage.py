from __future__ import annotations

import json

from creator_domain.models import MediaAsset
from pydantic import TypeAdapter

from . import db

_METADATA = TypeAdapter(dict[str, object])
_FILTER = """
    workspace_id = $1
    AND ($2::text IS NULL OR media_type = $2)
    AND ($3::integer IS NULL OR project_id = $3)
"""
_ORDER = """
    CASE origin WHEN 'UPLOADED' THEN 0 WHEN 'IMPORTED' THEN 1
        WHEN 'EXTERNAL_URL' THEN 2 WHEN 'STOCK' THEN 3 WHEN 'GENERATED' THEN 4
        ELSE 5 END,
    created_at DESC, id DESC
"""


class MediaAssetAssociationRejected(ValueError):
    """A referenced project or run does not belong to the asset's workspace/project."""


def _decode_asset(row: dict[str, object]) -> dict[str, object]:
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = _METADATA.validate_json(metadata)
    return MediaAsset.model_validate({**row, "metadata": metadata}).model_dump()


class PostgresMediaAssetStorage:
    async def save_asset(self, row: dict[str, object]) -> dict[str, object]:
        asset = MediaAsset.model_validate({**row, "id": 1})
        saved = await db.fetch_one(
            """
            INSERT INTO creator_media_assets (
                workspace_id, project_id, run_id, media_type, origin, storage_key,
                mime_type, width, height, duration_seconds, source_url, metadata, created_at
            )
            SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13
            WHERE ($2::integer IS NULL OR EXISTS (
                SELECT 1 FROM creator_projects WHERE id = $2 AND workspace_id = $1
            )) AND ($3::integer IS NULL OR EXISTS (
                SELECT 1 FROM creator_runs WHERE id = $3 AND workspace_id = $1
                    AND ($2::integer IS NULL OR project_id = $2)
            ))
            RETURNING *
            """,
            asset.workspace_id, asset.project_id, asset.run_id, asset.media_type.value,
            asset.origin.value, asset.storage_key, asset.mime_type, asset.width, asset.height,
            asset.duration_seconds, asset.source_url,
            json.dumps(asset.metadata, allow_nan=False), asset.created_at,
        )
        if saved is None:
            raise MediaAssetAssociationRejected("Media asset association not found")
        return _decode_asset(saved)

    async def get_asset(self, asset_id: int, workspace_id: int) -> dict[str, object] | None:
        row = await db.fetch_one(
            "SELECT * FROM creator_media_assets WHERE id = $1 AND workspace_id = $2",
            asset_id, workspace_id,
        )
        return _decode_asset(row) if row is not None else None

    async def list_assets(
        self, workspace_id: int, *, media_type: str | None = None,
        project_id: int | None = None, limit: int, offset: int,
    ) -> tuple[list[dict[str, object]], int]:
        pool = await db.get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                total = await connection.fetchval(
                    f"SELECT count(*) FROM creator_media_assets WHERE {_FILTER}",
                    workspace_id, media_type, project_id,
                )
                rows = await connection.fetch(
                    f"""SELECT * FROM creator_media_assets WHERE {_FILTER}
                        ORDER BY {_ORDER} LIMIT $4 OFFSET $5""",
                    workspace_id, media_type, project_id, limit, offset,
                )
        return [_decode_asset(dict(row)) for row in rows], int(total)
