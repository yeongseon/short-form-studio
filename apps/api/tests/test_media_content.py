"""Identity-based scene/workspace previews preserve the authorization boundary."""

from pathlib import Path
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from creator_domain.models.pipeline_run import PipelineRun
from creator_service.visual_asset_service import VisualAssetService


@pytest.fixture
async def media(client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from creator_service.run_service import run_service
    from creator_service.project_service import project_service
    from creator_domain.models.project import Project
    from creator_service.workspace_service import workspace_service
    from creator_service.visual_asset_service import visual_asset_service
    from creator_service.media_asset_service import media_asset_service

    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    visuals = VisualAssetService()
    monkeypatch.setattr(visual_asset_service, "storage", visuals.storage)
    async def get_run(run_id: int, workspace_id: int) -> PipelineRun | None:
        if run_id != 1 or workspace_id != 1:
            return None
        now = datetime.now(timezone.utc)
        return PipelineRun(id=1, project_id=1, current_stage="FINAL_REVIEW", status="running", created_at=now, updated_at=now)

    async def check_access(workspace_id: int, user_id: int) -> bool:
        return workspace_id == 1 and user_id == 1

    async def get_project(project_id: int, workspace_id: int) -> Project | None:
        if project_id != 1 or workspace_id != 1:
            return None
        now = datetime.now(timezone.utc)
        return Project(id=1, workspace_id=1, title="Media", created_at=now, updated_at=now)

    monkeypatch.setattr(run_service, "get_run", get_run)
    monkeypatch.setattr(project_service, "get_project", get_project)
    monkeypatch.setattr(workspace_service, "check_access", check_access)
    # Real in-memory stores and real bytes, with only identity lookup substituted.
    from creator_service.media_asset_service import InMemoryMediaAssetStorage
    storage = InMemoryMediaAssetStorage()
    monkeypatch.setattr(media_asset_service, "_asset_storage", storage)
    yield client, visuals, storage, tmp_path


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["development", "production", "staging"])
async def test_scene_content_when_authorized(media, monkeypatch, environment):
    client, visuals, _, root = media
    monkeypatch.setenv("ENVIRONMENT", environment)
    path = root / "scene.png"
    data = b"\x89PNG\r\n\x1a\nscene-bytes"
    path.write_bytes(data)
    asset = await visuals.create_asset(1, "scene-1", str(path))
    response = await client.get(f"/api/creator/runs/1/visual-assets/{asset.id}/content")
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
@pytest.mark.parametrize("run_id,asset_run", [(2, 1), (1, 2)])
async def test_scene_content_when_foreign(media, run_id, asset_run):
    client, visuals, _, root = media
    path = root / "scene.png"
    path.write_bytes(b"private")
    asset = await visuals.create_asset(asset_run, "scene-1", str(path))
    response = await client.get(f"/api/creator/runs/{run_id}/visual-assets/{asset.id}/content")
    assert response.status_code == 404
    assert b"private" not in response.content


@pytest.mark.asyncio
@pytest.mark.parametrize("path_kind", ["traversal", "absolute-outside", "symlink", "backslash"])
async def test_scene_content_when_path_escapes(media, path_kind):
    client, visuals, _, root = media
    outside = root.parent / f"{root.name}-private.png"
    outside.write_bytes(b"private")
    paths = {"traversal": f"../{outside.name}", "absolute-outside": str(outside),
             "backslash": f"..\\{outside.name}", "symlink": "link.png"}
    (root / "link.png").symlink_to(outside)
    asset = await visuals.create_asset(1, "scene-1", paths[path_kind])
    response = await client.get(f"/api/creator/runs/1/visual-assets/{asset.id}/content")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_scene_content_when_missing_or_unsafe_mime(media):
    client, visuals, _, root = media
    path = root / "scene.svg"
    path.write_text("<svg/>")
    asset = await visuals.create_asset(1, "scene-1", str(path))
    assert (await client.get(f"/api/creator/runs/1/visual-assets/{asset.id}/content")).status_code == 415
    assert (await client.get("/api/creator/runs/1/visual-assets/999/content")).status_code == 404


@pytest.mark.asyncio
async def test_workspace_content_when_authorized(media, monkeypatch):
    client, _, assets, root = media
    monkeypatch.setenv("ENVIRONMENT", "production")
    from creator_domain.models import MediaType, MediaOrigin
    path = root / "workspaces/1/assets/video.webm"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"video-bytes")
    asset = await assets.save_asset(dict(
        workspace_id=1, project_id=None, media_type=MediaType.VIDEO,
        origin=MediaOrigin.UPLOADED, storage_key="workspaces/1/assets/video.webm",
        mime_type="video/webm", created_at=datetime.now(timezone.utc),
    ))
    response = await client.get(f"/api/creator/workspaces/1/assets/{asset['id']}/content")
    assert response.status_code == 200
    assert response.content == b"video-bytes"
    assert response.headers["content-type"] == "video/webm"


@pytest.mark.asyncio
@pytest.mark.parametrize("workspace,owner", [(2, 1), (1, 2)])
async def test_workspace_content_when_foreign(media, workspace, owner):
    client, _, assets, _ = media
    asset = await assets.save_asset(dict(
        workspace_id=owner, project_id=None, media_type="IMAGE", origin="UPLOADED",
        storage_key="workspaces/2/private.png", mime_type="image/png", created_at=datetime.now(timezone.utc),
    ))
    response = await client.get(f"/api/creator/workspaces/{workspace}/assets/{asset['id']}/content")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_media_content_when_anonymous(media):
    client, _, _, _ = media
    for url in ["/api/creator/runs/1/visual-assets/1/content", "/api/creator/workspaces/1/assets/1/content"]:
        response = await client.get(url, headers={"X-API-Key": ""})
        assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["../private.png", "/tmp/private.png", "..\\private.png", "link.png"])
async def test_workspace_content_when_path_escapes(media, key):
    client, _, assets, root = media
    outside = root.parent / f"{root.name}-private.png"
    outside.write_bytes(b"private")
    (root / "link.png").symlink_to(outside)
    asset = await assets.save_asset(dict(
        workspace_id=1, media_type="IMAGE", origin="UPLOADED", storage_key=key,
        mime_type="image/png", created_at=datetime.now(timezone.utc),
    ))
    response = await client.get(f"/api/creator/workspaces/1/assets/{asset['id']}/content")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_workspace_content_when_missing_or_unsafe(media):
    client, _, assets, root = media
    (root / "unsafe.svg").write_text("<svg/>")
    asset = await assets.save_asset(dict(
        workspace_id=1, media_type="IMAGE", origin="UPLOADED", storage_key="unsafe.svg",
        mime_type="image/svg+xml", created_at=datetime.now(timezone.utc),
    ))
    assert (await client.get(f"/api/creator/workspaces/1/assets/{asset['id']}/content")).status_code == 415
    assert (await client.get("/api/creator/workspaces/1/assets/999/content")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["visual", "workspace"])
async def test_remote_content_is_not_interpreted_as_local(media, kind):
    client, visuals, assets, root = media
    (root / "scene.png").write_bytes(b"local-collision")
    if kind == "visual":
        asset = await visuals.create_asset(1, "scene-1", "scene.png", storage_provider="s3", storage_key="scene.png")
        url = f"/api/creator/runs/1/visual-assets/{asset.id}/content"
    else:
        row = await assets.save_asset(dict(
            workspace_id=1, media_type="IMAGE", origin="UPLOADED", storage_key="scene.png",
            mime_type="image/png", metadata={"storage_provider": "s3"}, created_at=datetime.now(timezone.utc),
        ))
        url = f"/api/creator/workspaces/1/assets/{row['id']}/content"
    assert (await client.get(url)).status_code == 409


@pytest.mark.asyncio
async def test_scene_storage_key_takes_precedence_over_legacy_path(media):
    client, visuals, _, root = media
    (root / "scene.png").write_bytes(b"selected-version")
    asset = await visuals.create_asset(1, "scene-1", "/obsolete/location.png", storage_key="scene.png")
    response = await client.get(f"/api/creator/runs/1/visual-assets/{asset.id}/content")
    assert response.content == b"selected-version"


@pytest.mark.asyncio
@pytest.mark.parametrize("filename,mime", [("voice.wav", "audio/wav"), ("captions.srt", "application/x-subrip"), ("page.html", "application/octet-stream")])
async def test_legacy_artifact_without_mime_uses_allowlisted_type(media, monkeypatch, filename, mime):
    from creator_service.artifact_download_service import artifact_download_service, InMemoryArtifactDownloadStorage
    client, _, _, root = media
    (root / filename).write_bytes(b"artifact-bytes")
    storage = InMemoryArtifactDownloadStorage()
    monkeypatch.setattr(artifact_download_service, "storage", storage)
    row = await storage.save_artifact({"run_id": 1, "storage_key": filename})
    response = await client.get(f"/api/creator/runs/1/artifacts/{row['id']}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == mime
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.content == b"artifact-bytes"
