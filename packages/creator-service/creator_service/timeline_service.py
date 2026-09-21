"""SF-28: persist one authoritative Timeline per authorized Project.

Storage split (Protocol -> InMemory -> Postgres via DATABASE_URL) mirrors
run_service/project_service. Optimistic concurrency uses the domain ``revision``
as the atomic counter: first save requires ``expected_revision == 0`` and yields
revision 1; later saves must match the current revision or a
``VersionConflictError`` is raised. Cross-asset references are validated against
a workspace+project-scoped asset owner lookup before any persistence.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Protocol

from creator_domain.exceptions import ValidationError, VersionConflictError
from creator_domain.models import Timeline


class AssetOwnerLookup(Protocol):
    """Resolve the project that owns an asset within a workspace.

    Returns the asset's ``project_id`` if the asset is visible in
    ``workspace_id``, else ``None`` (missing or cross-workspace).
    """

    async def get_asset_owner(self, asset_id: int, workspace_id: int) -> int | None: ...


class _MediaAssetOwnerAdapter:
    """Adapts MediaAssetService.get_asset to the AssetOwnerLookup protocol."""

    async def get_asset_owner(self, asset_id: int, workspace_id: int) -> int | None:
        from creator_service.media_asset_service import media_asset_service

        asset = await media_asset_service.get_asset(asset_id, workspace_id)
        if asset is None:
            return None
        return asset.project_id


class TimelineStorageBackend(Protocol):
    """Persistence for the one authoritative timeline per project."""

    async def save_timeline(
        self,
        *,
        project_id: int,
        workspace_id: int,
        timeline_id: str,
        segments_json: str,
        expected_revision: int,
    ) -> dict[str, Any] | None:
        """Atomically create/update the timeline row.

        Returns the persisted row (with the incremented ``revision``) on success,
        or ``None`` when the expected revision does not match (stale write).
        """
        ...

    async def load_timeline(
        self, *, project_id: int, workspace_id: int
    ) -> dict[str, Any] | None: ...


class InMemoryTimelineStorage:
    """In-memory timeline persistence with atomic revision semantics."""

    def __init__(self) -> None:
        self._rows: dict[int, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def save_timeline(
        self,
        *,
        project_id: int,
        workspace_id: int,
        timeline_id: str,
        segments_json: str,
        expected_revision: int,
    ) -> dict[str, Any] | None:
        async with self._lock:
            existing = self._rows.get(project_id)
            if existing is None:
                if expected_revision != 0:
                    return None
                row = {
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "timeline_id": timeline_id,
                    "revision": 1,
                    "segments_json": segments_json,
                }
                self._rows[project_id] = row
                return dict(row)
            if existing["workspace_id"] != workspace_id:
                return None
            if existing["revision"] != expected_revision:
                return None
            row = {
                **existing,
                "timeline_id": timeline_id,
                "segments_json": segments_json,
                "revision": existing["revision"] + 1,
            }
            self._rows[project_id] = row
            return dict(row)

    async def load_timeline(
        self, *, project_id: int, workspace_id: int
    ) -> dict[str, Any] | None:
        row = self._rows.get(project_id)
        if row is None or row["workspace_id"] != workspace_id:
            return None
        return dict(row)


class TimelineService:
    def __init__(
        self,
        storage: TimelineStorageBackend | None = None,
        *,
        asset_owner: AssetOwnerLookup | None = None,
    ) -> None:
        self._storage = storage or InMemoryTimelineStorage()
        self._asset_owner = asset_owner or _MediaAssetOwnerAdapter()

    async def _validate_asset_refs(
        self, *, project_id: int, workspace_id: int, timeline: Timeline
    ) -> None:
        asset_ids = {seg.asset_id for seg in timeline.segments}
        for asset_id in asset_ids:
            owner_project = await self._asset_owner.get_asset_owner(asset_id, workspace_id)
            if owner_project is None or owner_project != project_id:
                raise ValidationError("Timeline references unavailable asset(s)")

    async def save_timeline(
        self,
        *,
        project_id: int,
        workspace_id: int,
        timeline: Timeline,
        expected_revision: int,
    ) -> Timeline:
        if timeline.project_id != project_id:
            raise ValidationError("Timeline project_id does not match target project")
        await self._validate_asset_refs(
            project_id=project_id, workspace_id=workspace_id, timeline=timeline
        )

        segments_json = json.dumps(
            [seg.model_dump(mode="json") for seg in timeline.segments]
        )
        row = await self._storage.save_timeline(
            project_id=project_id,
            workspace_id=workspace_id,
            timeline_id=timeline.id,
            segments_json=segments_json,
            expected_revision=expected_revision,
        )
        if row is None:
            current = await self._storage.load_timeline(
                project_id=project_id, workspace_id=workspace_id
            )
            actual = current["revision"] if current is not None else 0
            raise VersionConflictError(project_id, expected_revision, actual)
        return self._row_to_timeline(row)

    async def load_timeline(
        self, *, project_id: int, workspace_id: int
    ) -> Timeline | None:
        row = await self._storage.load_timeline(
            project_id=project_id, workspace_id=workspace_id
        )
        if row is None:
            return None
        return self._row_to_timeline(row)

    @staticmethod
    def _row_to_timeline(row: dict[str, Any]) -> Timeline:
        return Timeline.model_validate(
            {
                "id": row["timeline_id"],
                "project_id": row["project_id"],
                "revision": row["revision"],
                "segments": json.loads(row["segments_json"]),
            }
        )


def _create_storage() -> TimelineStorageBackend:
    if os.getenv("DATABASE_URL"):
        from .postgres_timeline_storage import PostgresTimelineStorage

        return PostgresTimelineStorage()
    return InMemoryTimelineStorage()


timeline_service = TimelineService(_create_storage())
