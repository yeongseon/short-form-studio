from datetime import datetime, timezone
from pathlib import Path

import pytest
from creator_domain.models import EncodingProfile, MediaAsset, MediaOrigin, MediaType, OutputSpec, RenderPlan, RenderSegment, RenderSegmentKind
from creator_service.object_storage import LocalStorageBackend
from tasks.render_materializer import RenderSourceError, materialize_plan


@pytest.mark.parametrize("key", [
    "/etc/passwd", "../escape", "workspaces/7/assets/../escape",
    "workspaces/8/assets/foreign.png", "https://example.com/image.png",
    "workspaces/7/assets/a\\b", "workspaces/7/assets/a\x00b",
])
def test_materializer_rejects_unsafe_storage_keys(tmp_path: Path, key: str) -> None:
    asset = MediaAsset(
        id=1, workspace_id=7, project_id=11, media_type=MediaType.IMAGE,
        origin=MediaOrigin.GENERATED, storage_key=key, created_at=datetime.now(timezone.utc),
    )
    plan = RenderPlan(
        segments=[RenderSegment(kind=RenderSegmentKind.IMAGE, source=key,
                                timeline_start_seconds=0, duration_seconds=1)],
        output_spec=OutputSpec(width=96, height=160, fps=15), encoding_profile=EncodingProfile.preview(),
    )
    with pytest.raises(RenderSourceError):
        materialize_plan(plan, [asset], tmp_path, backend=LocalStorageBackend(str(tmp_path)), storage_provider="local")


def test_materializer_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    source_dir = root / "workspaces/7/assets"
    source_dir.mkdir(parents=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"must not be read")
    (source_dir / "linked.png").symlink_to(outside)
    key = "workspaces/7/assets/linked.png"
    asset = MediaAsset(
        id=1, workspace_id=7, project_id=11, media_type=MediaType.IMAGE,
        origin=MediaOrigin.GENERATED, storage_key=key, created_at=datetime.now(timezone.utc),
    )
    plan = RenderPlan(
        segments=[RenderSegment(kind=RenderSegmentKind.IMAGE, source=key,
                                timeline_start_seconds=0, duration_seconds=1)],
        output_spec=OutputSpec(width=96, height=160, fps=15), encoding_profile=EncodingProfile.preview(),
    )
    with pytest.raises(ValueError, match="traversal"):
        materialize_plan(plan, [asset], tmp_path, backend=LocalStorageBackend(str(root)), storage_provider="local")
