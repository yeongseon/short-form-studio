from __future__ import annotations

import io
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from creator_domain.models import MediaAsset, MediaOrigin, MediaType
from creator_service import db
from creator_service.media_asset_service import MediaAssetService
from creator_service.object_storage import LocalStorageBackend
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
