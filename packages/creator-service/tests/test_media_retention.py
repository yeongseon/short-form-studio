from __future__ import annotations

from datetime import datetime, timedelta, timezone

from creator_service.media_retention import (
    MediaRetentionService,
    MediaRetentionPolicy,
    RetentionAsset,
    select_retention_candidates,
)
from creator_service.object_storage import StorageDeletionError
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
async def test_storage_absent_object_removes_claimed_metadata() -> None:
    asset = _asset(1, 7, origin="GENERATED", media_type="IMAGE")

    class Storage:
        deleted: list[int] = []

        async def list_retention_assets(self, workspace_id: int, limit: int, *, after=None):
            return [asset]

        async def referenced_asset_ids(self, workspace_id: int):
            return frozenset()

        async def approved_asset_ids(self, workspace_id: int):
            return frozenset()

        async def retention_approvals_resolved(self, workspace_id: int):
            return True

        async def claim_retained_asset(self, asset_id: int, workspace_id: int):
            return "claim-token"

        async def release_retained_asset(self, asset_id: int, workspace_id: int, claim_token: str):
            self.deleted.append(-asset_id)

        async def finalize_retained_asset(
            self, asset_id: int, workspace_id: int, claim_token: str, delete_object,
        ):
            await delete_object()
            self.deleted.append(asset_id)
            return True

    class Objects:
        def delete(self, key: str) -> bool:
            return False

    storage = Storage()
    result = await MediaRetentionService(
        storage,
        Objects(),
        MediaRetentionPolicy(intermediate_days=7, enabled=True, dry_run=False),
    ).sweep_workspace(7, now=datetime.now(timezone.utc))

    assert result.deleted == 1
    assert storage.deleted == [1]


@pytest.mark.anyio
async def test_storage_delete_error_keeps_deletion_fence() -> None:
    # Given an eligible asset whose object deletion outcome is ambiguous.
    asset = _asset(1, 7, origin="GENERATED", media_type="IMAGE")

    class Storage:
        deleted: list[int] = []

        async def list_retention_assets(self, workspace_id: int, limit: int, *, after=None):
            return [asset]

        async def referenced_asset_ids(self, workspace_id: int):
            return frozenset()

        async def approved_asset_ids(self, workspace_id: int):
            return frozenset()

        async def retention_approvals_resolved(self, workspace_id: int):
            return True

        async def claim_retained_asset(self, asset_id: int, workspace_id: int):
            return "claim-token"

        async def release_retained_asset(self, asset_id: int, workspace_id: int, claim_token: str):
            self.deleted.append(-asset_id)

        async def finalize_retained_asset(
            self, asset_id: int, workspace_id: int, claim_token: str, delete_object,
        ):
            await delete_object()
            self.deleted.append(asset_id)
            return True

    class Objects:
        def delete(self, key: str) -> bool:
            raise StorageDeletionError(key)

    storage = Storage()

    # When the active retention sweep attempts physical deletion.
    with pytest.raises(StorageDeletionError):
        await MediaRetentionService(
            storage,
            Objects(),
            MediaRetentionPolicy(intermediate_days=7, enabled=True, dry_run=False),
        ).sweep_workspace(7, now=datetime.now(timezone.utc))

    # Then metadata remains accounted and the irreversible deletion fence stays owned.
    assert storage.deleted == []


@pytest.mark.anyio
async def test_retention_scans_past_full_page_of_protected_assets() -> None:
    # Given one eligible asset follows a full page of protected assets.
    assets = [_asset(asset_id, 7, origin="GENERATED", media_type="IMAGE") for asset_id in range(1, 102)]

    class Storage:
        deleted: list[int] = []

        async def list_retention_assets(self, workspace_id, limit, *, after=None):
            start = 0 if after is None else after.id
            return assets[start:start + limit]

        async def referenced_asset_ids(self, workspace_id):
            return frozenset(range(1, 101))

        async def approved_asset_ids(self, workspace_id):
            return frozenset()

        async def retention_approvals_resolved(self, workspace_id):
            return True

        async def claim_retained_asset(self, asset_id, workspace_id):
            return "claim-token"

        async def release_retained_asset(self, asset_id, workspace_id, claim_token):
            raise AssertionError

        async def finalize_retained_asset(
            self, asset_id, workspace_id, claim_token, delete_object,
        ):
            await delete_object()
            self.deleted.append(asset_id)
            return True

    class Objects:
        def delete(self, key: str) -> bool:
            return True

    storage = Storage()

    # When retention fills a deletion batch of one.
    result = await MediaRetentionService(
        storage,
        Objects(),
        MediaRetentionPolicy(intermediate_days=7, enabled=True, dry_run=False),
    ).sweep_workspace(7, now=datetime.now(timezone.utc), limit=1)

    # Then scanning advances beyond protected rows to the eligible asset.
    assert result.deleted == 1
    assert storage.deleted == [101]
