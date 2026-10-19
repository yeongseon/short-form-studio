from __future__ import annotations

import io
import os
import subprocess
import sys
import uuid
import anyio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anyio
import asyncpg
import pytest
import pytest_asyncio
from creator_domain.models import MediaAsset, MediaOrigin, MediaType
from creator_service import db
from creator_service.media_asset_service import MediaAssetService
from creator_service.media_upload_reconciliation import (
    MediaAssetPersistenceFailed,
    MediaUploadReconciler,
    UploadIntent,
    UploadIntentState,
)
from creator_service.object_storage import LocalStorageBackend
from creator_service.storage_policy import StorageBudgetExceeded, StoragePolicy
from PIL import Image


def image_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 12), (20, 40, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest_asyncio.fixture
async def media_database(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    url = os.getenv("MEDIA_ASSET_TEST_DATABASE_URL")
    if not url:
        pytest.skip("MEDIA_ASSET_TEST_DATABASE_URL must name an ephemeral test database")
    schema = f"media_test_{uuid.uuid4().hex}"
    root = Path(__file__).resolve().parents[3]
    async with asyncpg.create_pool(url, min_size=1, max_size=2) as admin:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        try:
            env = {**os.environ, "DATABASE_URL": url, "PGOPTIONS": f"-c search_path={schema}"}
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "033"],
                cwd=root / "apps/api", env=env, check=True, capture_output=True,
            )
            async with asyncpg.create_pool(
                url, min_size=1, max_size=2, server_settings={"search_path": schema},
            ) as pool:
                await pool.execute("""
                    INSERT INTO users (id, auth_subject) VALUES (9101, 'media-test');
                    INSERT INTO workspaces (id, name, slug, owner_id) VALUES
                        (9101, 'A', 'media-a', 9101), (9102, 'B', 'media-b', 9101);
                    INSERT INTO creator_projects (id, workspace_id) VALUES
                        (9101, 9101), (9102, 9102), (9103, 9101);
                    INSERT INTO creator_runs (id, project_id, workspace_id) VALUES
                        (9101, 9101, 9101), (9102, 9102, 9102);
                    INSERT INTO creator_scene_assets (id, run_id, scene_id, asset_path)
                        VALUES (9101, 9101, 'legacy', 'legacy/retained.png');
                """)
                subprocess.run(
                    [sys.executable, "-m", "alembic", "upgrade", "head"],
                    cwd=root / "apps/api", env=env, check=True, capture_output=True,
                )

                async def get_pool() -> asyncpg.Pool:
                    return pool

                monkeypatch.setattr(db, "get_pool", get_pool)
                monkeypatch.setenv("DATABASE_URL", f"{url}?search_path={schema}")
                yield
        finally:
            await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.mark.asyncio
async def test_asset_survives_new_process(media_database: None, tmp_path: Path) -> None:
    # Given a real database and a first service that stores actual bytes.
    backend = LocalStorageBackend(str(tmp_path))
    first = MediaAssetService(storage_backend=backend)
    asset = await first.create_image_asset(
        workspace_id=9101, project_id=9101, filename="persist.png",
        data=image_bytes(), content_type="image/png",
    )
    # When a separate interpreter and connection pool read persisted metadata.
    root = Path(__file__).resolve().parents[3]
    package_paths = os.pathsep.join(str(root / "packages" / name) for name in (
        "creator-domain", "creator-service", "creator-provider",
    ))
    result = subprocess.run(
        [sys.executable, "-c", """
import sys
import anyio
from creator_service import db
from creator_service.media_asset_service import MediaAssetService

async def main():
    try:
        asset = await MediaAssetService().get_asset(int(sys.argv[1]), 9101)
        assert asset is not None
        print(asset.model_dump_json())
    finally:
        await db.close_pool()

anyio.run(main)
""", str(asset.id)],
        check=True, capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONPATH": package_paths},
    )
    restored = MediaAsset.model_validate_json(result.stdout)
    # Then metadata is durable and scoped, while byte access remains unchanged.
    assert restored == asset
    assert restored is not None and restored.storage_key is not None
    assert backend.download_bytes(restored.storage_key) == image_bytes()
    assert await first.get_asset(asset.id, 9102) is None
    assert (await first.list_assets(workspace_id=9102)).total == 0


@pytest.mark.asyncio
async def test_generated_metadata_roundtrips_json(media_database: None, tmp_path: Path) -> None:
    # Given generated PNG data with nested annotations.
    service = MediaAssetService(storage_backend=LocalStorageBackend(str(tmp_path)))
    created = await service.create_generated_image_asset(
        workspace_id=9101, project_id=9101, filename="demo.png", data=image_bytes(),
        metadata={"nested": {"label": "샘플", "flags": [True, None, 1.25]}},
    )
    # When another service reads its database metadata.
    restored = await MediaAssetService().get_asset(created.id, 9101)
    # Then typed fields, timestamps and JSON retain their values.
    assert restored == created
    assert restored is not None and restored.origin is MediaOrigin.GENERATED


@pytest.mark.asyncio
async def test_postgres_pagination_matches_memory_contract(media_database: None, tmp_path: Path) -> None:
    # Given mixed origins, media types, projects and tied timestamps.
    service = MediaAssetService(storage_backend=LocalStorageBackend(str(tmp_path)))
    initial = await service.create_image_asset(
        workspace_id=9101, project_id=9101, filename="a.png",
        data=image_bytes(), content_type="image/png",
    )
    cases = [
        (MediaType.IMAGE, MediaOrigin.GENERATED, 9101),
        (MediaType.IMAGE, MediaOrigin.UPLOADED, 9101),
        (MediaType.AUDIO, MediaOrigin.UPLOADED, 9101),
        (MediaType.IMAGE, MediaOrigin.UPLOADED, 9103),
    ]
    assets = [initial]
    for media_type, origin, project_id in cases:
        row = initial.model_dump(exclude={"id"})
        row.update(media_type=media_type.value, origin=origin.value, project_id=project_id)
        assets.append(MediaAsset.model_validate(await service._asset_storage.save_asset(row)))
    # When querying a filtered page and an offset past the last page.
    page = await service.list_assets(workspace_id=9101, project_id=9101, media_type=MediaType.IMAGE)
    empty = await service.list_assets(
        workspace_id=9101, project_id=9101, media_type=MediaType.IMAGE, offset=99,
    )
    # Then sorting, totals and filtering agree even on an empty page.
    assert [asset.id for asset in page.items] == [assets[2].id, initial.id, assets[1].id]
    assert page.total == empty.total == 3
    assert empty.items == []


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [{"project_id": 9102}, {"run_id": 9102}, {"project_id": 9103, "run_id": 9101}])
async def test_postgres_rejects_foreign_associations(
    media_database: None, tmp_path: Path, overrides: dict[str, int],
) -> None:
    # Given a valid asset row with a forged project or run association.
    service = MediaAssetService(storage_backend=LocalStorageBackend(str(tmp_path)))
    asset = await service.create_image_asset(
        workspace_id=9101, project_id=9101, filename="a.png", data=image_bytes(), content_type="image/png",
    )
    row = {**asset.model_dump(exclude={"id"}), **overrides}
    # When directly saving through the metadata adapter.
    with pytest.raises(ValueError):
        await service._asset_storage.save_asset(row)
    # Then a forged association did not create another asset.
    assert (await service.list_assets(workspace_id=9101)).total == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"project_id": 9999},
        {"project_id": 9102},
        {"run_id": 9999},
        {"run_id": 9102},
    ],
)
async def test_failed_uploaded_asset_association_remains_reconcilable(
    media_database: None, tmp_path: Path, overrides: dict[str, int],
) -> None:
    # Given an uploaded object and intent whose project or run association is unavailable.
    storage = MediaAssetService()._asset_storage
    objects = LocalStorageBackend(str(tmp_path))
    now = datetime.now(timezone.utc)
    intent = await storage.create_upload_intent(UploadIntent(
        id=0, owner_id=uuid.uuid4().hex, workspace_id=9101,
        storage_key=f"workspaces/9101/assets/{uuid.uuid4().hex}.png",
        state=UploadIntentState.PENDING, lease_expires_at=now,
    ))
    objects.upload(intent.storage_key, image_bytes(), content_type="image/png")
    await storage.mark_upload_intent_uploaded(intent.id)
    row = {
        "workspace_id": 9101,
        "project_id": 9101,
        "run_id": None,
        "media_type": MediaType.IMAGE.value,
        "origin": MediaOrigin.UPLOADED.value,
        "storage_key": intent.storage_key,
        "mime_type": "image/png",
        "width": 8,
        "height": 12,
        "duration_seconds": None,
        "source_url": None,
        "metadata": {},
        "created_at": now,
        **overrides,
    }

    # When atomic metadata persistence rejects the association.
    with pytest.raises(MediaAssetPersistenceFailed):
        await storage.save_uploaded_asset(row, intent)

    # Then the intent remains sweepable and reconciliation deletes the orphan.
    persisted = await db.fetch_one(
        "SELECT state FROM creator_media_upload_intents WHERE id = $1", intent.id,
    )
    assert persisted == {"state": "uploaded"}
    await db.execute(
        "UPDATE creator_media_upload_intents SET lease_expires_at = $2 WHERE id = $1",
        intent.id, now,
    )
    await MediaUploadReconciler(objects, storage).sweep(now=now)
    assert not (tmp_path / intent.storage_key).exists()


@pytest.mark.asyncio
async def test_additive_migration_retains_legacy_assets(media_database: None) -> None:
    # Given a legacy scene asset inserted before the new migration.
    # When reading the old storage table after upgrading.
    row = await db.fetch_one("SELECT asset_path FROM creator_scene_assets WHERE id = $1", 9101)
    # Then existing data remains accessible without an ID remap.
    assert row == {"asset_path": "legacy/retained.png"}


@pytest.mark.asyncio
async def test_postgres_preserves_all_domain_media_types(media_database: None, tmp_path: Path) -> None:
    # Given a valid metadata row for each supported domain media type.
    service = MediaAssetService(storage_backend=LocalStorageBackend(str(tmp_path)))
    initial = await service.create_image_asset(
        workspace_id=9101, filename="a.png", data=image_bytes(), content_type="image/png",
    )
    # When persisting every domain variant, including logos and graphics.
    saved = [
        MediaAsset.model_validate(await service._asset_storage.save_asset({
            **initial.model_dump(exclude={"id"}), "media_type": kind.value,
        }))
        for kind in MediaType
    ]
    # Then storage supports the complete domain rather than only upload routes.
    assert [asset.media_type for asset in saved] == list(MediaType)


@pytest.mark.asyncio
async def test_postgres_upload_intent_is_durable_and_workspace_owned(media_database: None) -> None:
    # Given an upload intent created before object I/O.
    storage = MediaAssetService()._asset_storage
    now = datetime.now(timezone.utc)
    intent = await storage.create_upload_intent(UploadIntent(
        id=0, owner_id=uuid.uuid4().hex, workspace_id=9101,
        storage_key="workspaces/9101/assets/pending.png",
        state=UploadIntentState.PENDING, lease_expires_at=now,
    ))

    # When an expired reconciliation lease is claimed and terminally completed.
    claimed = await storage.claim_expired_upload_intents(
        now=now, lease_expires_at=now + timedelta(minutes=5), limit=10,
    )
    await storage.record_upload_reclaimed(intent.id, claimed[0].claim_token)

    # Then the exact owned record was claimed once and remains durable.
    assert [candidate.id for candidate in claimed] == [intent.id]
    row = await db.fetch_one(
        "SELECT state, workspace_id, storage_key FROM creator_media_upload_intents WHERE id = $1",
        intent.id,
    )
    assert row == {
        "state": "reclaimed", "workspace_id": 9101,
        "storage_key": "workspaces/9101/assets/pending.png",
    }


@pytest.mark.asyncio
async def test_postgres_claim_is_skip_locked_and_fences_uploader_cas(media_database: None) -> None:
    # Given one expired upload intent and two concurrent reconciliation workers.
    storage = MediaAssetService()._asset_storage
    now = datetime.now(timezone.utc)
    intent = await storage.create_upload_intent(UploadIntent(
        id=0, owner_id=uuid.uuid4().hex, workspace_id=9101,
        storage_key="workspaces/9101/assets/racing.png",
        state=UploadIntentState.PENDING, lease_expires_at=now,
    ))
    claims: list[list[UploadIntent]] = []

    async def claim() -> None:
        claims.append(await storage.claim_expired_upload_intents(
            now=now, lease_expires_at=now + timedelta(minutes=5), limit=1,
        ))

    # When both workers claim via SKIP LOCKED and the uploader attempts its CAS.
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(claim)
        tasks.start_soon(claim)

    # Then exactly one worker owns a claim and the stale uploader is fenced out.
    assert sorted(len(claimed) for claimed in claims) == [0, 1]
    with pytest.raises(MediaAssetPersistenceFailed):
        await storage.mark_upload_intent_uploaded(intent.id)


@pytest.mark.asyncio
async def test_postgres_expired_claim_replacement_fences_stale_updates(media_database: None) -> None:
    # Given a PostgreSQL reconciliation claim that expires before completion.
    storage = MediaAssetService()._asset_storage
    now = datetime.now(timezone.utc)
    intent = await storage.create_upload_intent(UploadIntent(
        id=0, owner_id=uuid.uuid4().hex, workspace_id=9101,
        storage_key="workspaces/9101/assets/stranded.png",
        state=UploadIntentState.PENDING, lease_expires_at=now,
    ))
    first = (await storage.claim_expired_upload_intents(
        now=now, lease_expires_at=now, limit=1,
    ))[0]

    # When a successor atomically replaces the expired claim token.
    successor = (await storage.claim_expired_upload_intents(
        now=now, lease_expires_at=now + timedelta(minutes=5), limit=1,
    ))[0]

    # Then stale terminal/failure writes cannot overwrite successor ownership.
    assert successor.claim_token != first.claim_token
    with pytest.raises(MediaAssetPersistenceFailed):
        await storage.record_upload_reclaimed(intent.id, first.claim_token)
    with pytest.raises(MediaAssetPersistenceFailed):
        await storage.record_upload_cleanup_failure(intent.id, 5, first.claim_token)
    await storage.record_upload_reclaimed(intent.id, successor.claim_token)


@pytest.mark.asyncio
async def test_postgres_successor_claim_retains_watch_for_late_materialization(
    media_database: None, tmp_path: Path,
) -> None:
    # Given sweeper A claims a pending upload and dies before recording its observation.
    storage = MediaAssetService()._asset_storage
    objects = LocalStorageBackend(str(tmp_path))
    now = datetime.now(timezone.utc)
    intent = await storage.create_upload_intent(UploadIntent(
        id=0, owner_id=uuid.uuid4().hex, workspace_id=9101,
        storage_key="workspaces/9101/assets/claim-replacement.png",
        state=UploadIntentState.PENDING, lease_expires_at=now,
    ))
    await storage.claim_expired_upload_intents(
        now=now, lease_expires_at=now, limit=1,
    )

    # When successor B replaces the expired claim before the object materializes.
    replacement = await MediaUploadReconciler(objects, storage).sweep(now=now)
    objects.upload(intent.storage_key, image_bytes(), content_type="image/png")
    later = now + timedelta(hours=1)
    await db.execute(
        "UPDATE creator_media_upload_intents SET lease_expires_at = $2 WHERE id = $1",
        intent.id, later,
    )
    final = await MediaUploadReconciler(objects, storage).sweep(now=later)

    # Then B retained a watch and the later sweep deletes the orphan.
    assert replacement.reclaimed == 0
    assert final.reclaimed == 0
    assert not (tmp_path / intent.storage_key).exists()
    row = await db.fetch_one(
        "SELECT state FROM creator_media_upload_intents WHERE id = $1", intent.id,
    )
    assert row == {"state": "late_upload_watch"}


@pytest.mark.asyncio
async def test_postgres_late_upload_after_absent_observation_is_deleted(
    media_database: None, tmp_path: Path,
) -> None:
    # Given PostgreSQL retains an expired pending intent after observing no object.
    storage = MediaAssetService()._asset_storage
    objects = LocalStorageBackend(str(tmp_path))
    now = datetime.now(timezone.utc)
    intent = await storage.create_upload_intent(UploadIntent(
        id=0, owner_id=uuid.uuid4().hex, workspace_id=9101,
        storage_key="workspaces/9101/assets/late-process-death.png",
        state=UploadIntentState.PENDING, lease_expires_at=now,
    ))
    first = await MediaUploadReconciler(objects, storage).sweep(now=now)

    # When retention elapses while absent, then the object appears without an uploader update.
    retention = now + timedelta(hours=1)
    await db.execute(
        "UPDATE creator_media_upload_intents SET lease_expires_at = $2 WHERE id = $1",
        intent.id, retention,
    )
    absent = await MediaUploadReconciler(objects, storage).sweep(now=retention)
    objects.upload(intent.storage_key, image_bytes(), content_type="image/png")
    later = retention + timedelta(minutes=5)
    await db.execute(
        "UPDATE creator_media_upload_intents SET lease_expires_at = $2 WHERE id = $1",
        intent.id, later,
    )
    second = await MediaUploadReconciler(objects, storage).sweep(now=later)
    # Then PostgreSQL retains ownership while absent and later deletes the object.
    assert first.reclaimed == 0
    assert absent.reclaimed == 0
    assert second.reclaimed == 0
    assert not (tmp_path / intent.storage_key).exists()
    row = await db.fetch_one(
        "SELECT state FROM creator_media_upload_intents WHERE id = $1", intent.id,
    )
    assert row == {"state": "late_upload_watch"}


@pytest.mark.asyncio
async def test_postgres_successful_delete_keeps_watch_for_rematerialized_upload(
    media_database: None, tmp_path: Path,
) -> None:
    # Given an expired pending upload whose object already exists in local storage.
    storage = MediaAssetService()._asset_storage
    objects = LocalStorageBackend(str(tmp_path))
    now = datetime.now(timezone.utc)
    intent = await storage.create_upload_intent(UploadIntent(
        id=0, owner_id=uuid.uuid4().hex, workspace_id=9101,
        storage_key="workspaces/9101/assets/rematerialized.png",
        state=UploadIntentState.PENDING, lease_expires_at=now,
    ))
    objects.upload(intent.storage_key, image_bytes(), content_type="image/png")

    # When a sweep deletes it, then a still-running uploader rewrites the same key.
    first = await MediaUploadReconciler(objects, storage).sweep(now=now)
    objects.upload(intent.storage_key, image_bytes(), content_type="image/png")
    later = now + timedelta(hours=1)
    await db.execute(
        "UPDATE creator_media_upload_intents SET lease_expires_at = $2 WHERE id = $1",
        intent.id, later,
    )
    second = await MediaUploadReconciler(objects, storage).sweep(now=later)

    # Then PostgreSQL retains the watch and the later sweep removes the rewrite.
    assert first.reclaimed == 0
    assert second.reclaimed == 0
    assert not (tmp_path / intent.storage_key).exists()
    row = await db.fetch_one(
        "SELECT state FROM creator_media_upload_intents WHERE id = $1", intent.id,
    )
    assert row == {"state": "late_upload_watch"}

    # When the object materializes after the former 24-hour watch cutoff.
    former_cutoff = now + timedelta(hours=24)
    await db.execute(
        """UPDATE creator_media_upload_intents
            SET created_at = $2, lease_expires_at = $3 WHERE id = $1""",
        intent.id, now, former_cutoff,
    )
    absent = await MediaUploadReconciler(objects, storage).sweep(now=former_cutoff)
    objects.upload(intent.storage_key, image_bytes(), content_type="image/png")
    later = former_cutoff + timedelta(hours=1)
    await db.execute(
        "UPDATE creator_media_upload_intents SET lease_expires_at = $2 WHERE id = $1",
        intent.id, later,
    )
    final = await MediaUploadReconciler(objects, storage).sweep(now=later)

    # Then PostgreSQL keeps the tombstone and removes the late materialization.
    assert absent.reclaimed == 0
    assert final.reclaimed == 0
    assert not (tmp_path / intent.storage_key).exists()
    row = await db.fetch_one(
        "SELECT state FROM creator_media_upload_intents WHERE id = $1", intent.id,
    )
    assert row == {"state": "late_upload_watch"}
@pytest.mark.asyncio
async def test_postgres_concurrent_admission_stays_within_budget(media_database: None) -> None:
    storage = MediaAssetService()._asset_storage
    policy = StoragePolicy(max_stored_bytes=10, max_asset_count=10, max_reserved_bytes=10)
    now = datetime.now(timezone.utc)

    async def reserve(owner_id: str) -> bool:
        try:
            await storage.create_upload_intent(
                UploadIntent(
                    id=0, owner_id=owner_id, workspace_id=9101,
                    storage_key=f"workspaces/9101/assets/{owner_id}.png",
                    state=UploadIntentState.PENDING, lease_expires_at=now,
                    reserved_bytes=6,
                ),
                policy=policy,
            )
        except StorageBudgetExceeded:
            return False
        return True

    results: list[bool] = []

    async def collect(owner_id: str) -> None:
        results.append(await reserve(owner_id))

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(collect, "budget-a")
        tasks.start_soon(collect, "budget-b")

    assert sorted(results) == [False, True]


@pytest.mark.asyncio
async def test_postgres_crash_claim_remains_reserved_until_terminal_reclaim(
    media_database: None,
) -> None:
    # Given a reservation that has expired without an upload completing.
    storage = MediaAssetService()._asset_storage
    policy = StoragePolicy(max_stored_bytes=10, max_asset_count=1, max_reserved_bytes=10)
    now = datetime.now(timezone.utc)
    intent = await storage.create_upload_intent(
        UploadIntent(
            id=0, owner_id="crashed", workspace_id=9101,
            storage_key="workspaces/9101/assets/crashed.png",
            state=UploadIntentState.PENDING, lease_expires_at=now,
            reserved_bytes=10,
        ),
        policy=policy,
    )

    # When the crash sweeper claims the reservation for cleanup.
    claimed = await storage.claim_expired_upload_intents(
        now=now, lease_expires_at=now + timedelta(minutes=5), limit=1,
    )

    # Then concurrent admission stays blocked until the owned claim is terminal.
    with pytest.raises(StorageBudgetExceeded):
        await storage.create_upload_intent(
            UploadIntent(
                id=0, owner_id="replacement", workspace_id=9101,
                storage_key="workspaces/9101/assets/replacement.png",
                state=UploadIntentState.PENDING,
                lease_expires_at=now + timedelta(minutes=30), reserved_bytes=1,
            ),
            policy=policy,
        )
    await storage.record_upload_reclaimed(intent.id, claimed[0].claim_token)
    usage = await storage.get_storage_usage(9101, policy=policy)
    assert usage.reserved_bytes == 0
