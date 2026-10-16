from __future__ import annotations

from datetime import datetime, timedelta, timezone

from creator_service.media_retention import (
    MediaRetentionService,
    MediaRetentionPolicy,
    RetentionAsset,
    select_retention_candidates,
)
import pytest


def _asset(asset_id: int, workspace_id: int, *, origin: str, media_type: str) -> RetentionAsset:
    return RetentionAsset(
        id=asset_id,
        workspace_id=workspace_id,
        storage_key=f"workspaces/{workspace_id}/assets/{asset_id}",
        origin=origin,
        media_type=media_type,
        created_at=datetime.now(timezone.utc) - timedelta(days=100),
    )


def test_retention_is_disabled_without_explicit_windows() -> None:
    candidates = select_retention_candidates(
        [_asset(1, 7, origin="UPLOADED", media_type="IMAGE")],
        policy=MediaRetentionPolicy(),
        referenced_asset_ids=frozenset(),
        approved_asset_ids=frozenset(),
        workspace_id=7,
        now=datetime.now(timezone.utc),
    )
    assert candidates == []


def test_retention_preserves_references_approved_revisions_and_other_workspaces() -> None:
    policy = MediaRetentionPolicy(original_days=30, intermediate_days=7, final_video_days=60)
    assets = [
        _asset(1, 7, origin="UPLOADED", media_type="IMAGE"),
        _asset(2, 7, origin="GENERATED", media_type="IMAGE"),
        _asset(3, 7, origin="GENERATED", media_type="VIDEO"),
        _asset(4, 8, origin="GENERATED", media_type="IMAGE"),
    ]

    candidates = select_retention_candidates(
        assets,
        policy=policy,
        referenced_asset_ids=frozenset({1}),
        approved_asset_ids=frozenset({3}),
        workspace_id=7,
        now=datetime.now(timezone.utc),
    )

    assert [candidate.id for candidate in candidates] == [2]


@pytest.mark.anyio
async def test_storage_delete_failure_keeps_metadata_accounted() -> None:
    asset = _asset(1, 7, origin="GENERATED", media_type="IMAGE")

    class Storage:
        deleted: list[int] = []

        async def list_retention_assets(self, workspace_id: int, limit: int):
            return [asset]

        async def referenced_asset_ids(self, workspace_id: int):
            return frozenset()

        async def approved_asset_ids(self, workspace_id: int):
            return frozenset()

        async def delete_retained_asset(self, asset_id: int, workspace_id: int):
            self.deleted.append(asset_id)

    class Objects:
        def delete(self, key: str) -> bool:
            return False

    storage = Storage()
    result = await MediaRetentionService(
        storage,
        Objects(),
        MediaRetentionPolicy(intermediate_days=7, enabled=True, dry_run=False),
    ).sweep_workspace(7, now=datetime.now(timezone.utc))

    assert result.deleted == 0
    assert storage.deleted == []
