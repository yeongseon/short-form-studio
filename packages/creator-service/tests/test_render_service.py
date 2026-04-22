import asyncio
from dataclasses import dataclass

import pytest
from creator_service.render_service import (
    InMemoryRenderStorage,
    RenderService,
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def storage() -> InMemoryRenderStorage:
    return InMemoryRenderStorage()


@pytest.fixture
def service(storage: InMemoryRenderStorage) -> RenderService:
    return RenderService(storage)


# -- Fake dependencies for build_render_manifest tests -----------------------


@dataclass
class FakeVisualAsset:
    scene_id: str
    asset_path: str
    prompt_snapshot: str
    is_active: bool


class FakeVisualAssetService:
    def __init__(self, grouped: dict[str, list[FakeVisualAsset]]):
        self._grouped = grouped

    async def list_by_run(self, run_id: int) -> dict[str, list[FakeVisualAsset]]:
        return self._grouped


@dataclass
class FakeAudioArtifact:
    path: str


class FakeAudioService:
    def __init__(self, artifact=None):
        self._artifact = artifact

    async def get_latest(self, run_id):
        return self._artifact


@dataclass
class FakeSubtitleArtifact:
    path: str


class FakeSubtitleService:
    def __init__(self, artifact=None):
        self._artifact = artifact

    async def get_latest(self, run_id):
        return self._artifact


# -- create_artifact ---------------------------------------------------------------


def test_create_artifact(service: RenderService) -> None:
    artifact = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/render.mp4",
        )
    )

    assert artifact.run_id == 1
    assert artifact.path == "/data/artifacts/1/render.mp4"
    assert artifact.render_profile is None
    assert artifact.created_at is not None


def test_create_artifact_with_render_profile_metadata(service: RenderService) -> None:
    artifact = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/render.mp4",
            render_profile="high_quality",
        )
    )

    assert artifact.run_id == 1
    assert artifact.path == "/data/artifacts/1/render.mp4"
    assert artifact.render_profile == "high_quality"
    assert artifact.created_at is not None


def test_create_artifact_has_id(service: RenderService) -> None:
    artifact = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/render.mp4",
        )
    )

    assert artifact.id is not None
    assert artifact.id > 0


# -- get_latest ---------------------------------------------------------------


def test_get_latest_returns_most_recent(service: RenderService) -> None:
    """Create 2 artifacts, get_latest returns newest."""
    first = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/render_v1.mp4",
        )
    )
    second = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/render_v2.mp4",
        )
    )

    latest = run(service.get_latest(run_id=1))

    assert latest is not None
    assert latest.id == second.id
    assert latest.id != first.id
    assert latest.path == "/data/artifacts/1/render_v2.mp4"


def test_get_latest_empty(service: RenderService) -> None:
    """Returns None when no artifacts."""
    latest = run(service.get_latest(run_id=999))

    assert latest is None


# -- list_by_run ---------------------------------------------------------------


def test_list_by_run_newest_first(service: RenderService) -> None:
    """Multiple artifacts, sorted by created_at desc."""
    a1 = run(service.create_artifact(run_id=1, path="/render_1.mp4"))
    a2 = run(service.create_artifact(run_id=1, path="/render_2.mp4"))
    a3 = run(service.create_artifact(run_id=1, path="/render_3.mp4"))

    artifacts = run(service.list_by_run(run_id=1))

    assert len(artifacts) == 3
    assert artifacts[0].id == a3.id
    assert artifacts[1].id == a2.id
    assert artifacts[2].id == a1.id


def test_list_by_run_empty(service: RenderService) -> None:
    """Returns empty list."""
    artifacts = run(service.list_by_run(run_id=999))

    assert artifacts == []


def test_list_by_run_filters_by_run(service: RenderService) -> None:
    """Create for run_id=1 and run_id=2, verify isolation."""
    run(service.create_artifact(run_id=1, path="/run1_render.mp4"))
    run(service.create_artifact(run_id=1, path="/run1_render_v2.mp4"))
    run(service.create_artifact(run_id=2, path="/run2_render.mp4"))

    run1_artifacts = run(service.list_by_run(run_id=1))
    run2_artifacts = run(service.list_by_run(run_id=2))

    assert len(run1_artifacts) == 2
    assert len(run2_artifacts) == 1
    assert all(a.run_id == 1 for a in run1_artifacts)
    assert all(a.run_id == 2 for a in run2_artifacts)


# -- get_by_id ---------------------------------------------------------------


def test_get_by_id(service: RenderService) -> None:
    """Fetch by specific id."""
    created = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/render.mp4",
        )
    )

    fetched = run(service.get_by_id(created.id))

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.path == "/data/artifacts/1/render.mp4"


def test_get_by_id_not_found(service: RenderService) -> None:
    """Returns None for nonexistent id."""
    fetched = run(service.get_by_id(999))

    assert fetched is None


# -- Concurrent saves -----------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_saves_produce_unique_ids() -> None:
    """Two concurrent saves must produce distinct ids."""
    storage = InMemoryRenderStorage()
    svc = RenderService(storage)

    results = await asyncio.gather(
        svc.create_artifact(run_id=1, path="/a.mp4"),
        svc.create_artifact(run_id=1, path="/b.mp4"),
    )

    ids = sorted(a.id for a in results)
    assert ids == [1, 2], f"Expected unique ids [1, 2], got {ids}"


# -- Isolation -------------------------------------------------------------------


def test_different_runs_have_independent_artifacts(service: RenderService) -> None:
    run(service.create_artifact(run_id=1, path="/r1_render.mp4"))
    run(service.create_artifact(run_id=2, path="/r2_render.mp4"))

    r1_artifacts = run(service.list_by_run(run_id=1))
    r2_artifacts = run(service.list_by_run(run_id=2))

    assert len(r1_artifacts) == 1
    assert len(r2_artifacts) == 1
    assert r1_artifacts[0].run_id == 1
    assert r2_artifacts[0].run_id == 2


def test_create_artifact_incremental_ids(service: RenderService) -> None:
    """IDs should increment sequentially."""
    a1 = run(service.create_artifact(run_id=1, path="/render1.mp4"))
    a2 = run(service.create_artifact(run_id=1, path="/render2.mp4"))
    a3 = run(service.create_artifact(run_id=2, path="/render3.mp4"))

    assert a1.id == 1
    assert a2.id == 2
    assert a3.id == 3


# -- build_render_manifest -------------------------------------------------------


@pytest.mark.asyncio
async def test_build_render_manifest_with_assets_audio_subtitles() -> None:
    """Test build_render_manifest with all dependencies."""
    service = RenderService()

    # Create fake dependencies
    grouped_assets = {
        "scene_1": [
            FakeVisualAsset(
                scene_id="scene_1",
                asset_path="/path/to/scene_1_asset.png",
                prompt_snapshot="A beautiful sunset",
                is_active=True,
            ),
        ],
        "scene_2": [
            FakeVisualAsset(
                scene_id="scene_2",
                asset_path="/path/to/scene_2_asset.png",
                prompt_snapshot="Ocean waves",
                is_active=True,
            ),
        ],
    }

    visual_service = FakeVisualAssetService(grouped_assets)
    audio_service = FakeAudioService(FakeAudioArtifact(path="/path/to/audio.wav"))
    subtitle_service = FakeSubtitleService(FakeSubtitleArtifact(path="/path/to/subs.srt"))

    manifest = await service.build_render_manifest(
        run_id=1,
        visual_asset_service=visual_service,
        audio_service=audio_service,
        subtitle_service=subtitle_service,
        render_profile_name="shorts_default",
    )

    assert manifest["run_id"] == 1
    assert len(manifest["scenes"]) == 2
    assert manifest["scenes"][0]["scene_id"] == "scene_1"
    assert manifest["scenes"][0]["asset_path"] == "/path/to/scene_1_asset.png"
    assert manifest["scenes"][0]["prompt_snapshot"] == "A beautiful sunset"
    assert manifest["audio_path"] == "/path/to/audio.wav"
    assert manifest["subtitle_path"] == "/path/to/subs.srt"
    assert manifest["render_profile"]["name"] == "shorts_default"
    assert manifest["render_profile"]["width"] == 1080
    assert manifest["render_profile"]["height"] == 1920


@pytest.mark.asyncio
async def test_build_render_manifest_without_audio_subtitles() -> None:
    """Test build_render_manifest when audio/subtitles are None."""
    service = RenderService()

    grouped_assets = {
        "scene_1": [
            FakeVisualAsset(
                scene_id="scene_1",
                asset_path="/path/to/scene_1_asset.png",
                prompt_snapshot="A beautiful sunset",
                is_active=True,
            ),
        ],
    }

    visual_service = FakeVisualAssetService(grouped_assets)
    audio_service = FakeAudioService(None)
    subtitle_service = FakeSubtitleService(None)

    manifest = await service.build_render_manifest(
        run_id=1,
        visual_asset_service=visual_service,
        audio_service=audio_service,
        subtitle_service=subtitle_service,
    )

    assert manifest["run_id"] == 1
    assert len(manifest["scenes"]) == 1
    assert manifest["audio_path"] is None
    assert manifest["subtitle_path"] is None
    assert manifest["render_profile"]["name"] == "shorts_default"


@pytest.mark.asyncio
async def test_build_render_manifest_with_empty_scenes() -> None:
    """Test build_render_manifest with no active assets."""
    service = RenderService()

    grouped_assets = {}

    visual_service = FakeVisualAssetService(grouped_assets)
    audio_service = FakeAudioService(FakeAudioArtifact(path="/path/to/audio.wav"))
    subtitle_service = FakeSubtitleService(None)

    manifest = await service.build_render_manifest(
        run_id=1,
        visual_asset_service=visual_service,
        audio_service=audio_service,
        subtitle_service=subtitle_service,
    )

    assert manifest["run_id"] == 1
    assert manifest["scenes"] == []
    assert manifest["audio_path"] == "/path/to/audio.wav"
    assert manifest["subtitle_path"] is None


@pytest.mark.asyncio
async def test_build_render_manifest_high_quality_profile() -> None:
    """Test build_render_manifest with high_quality profile."""
    service = RenderService()

    grouped_assets = {
        "scene_1": [
            FakeVisualAsset(
                scene_id="scene_1",
                asset_path="/asset.png",
                prompt_snapshot="test",
                is_active=True,
            ),
        ],
    }

    visual_service = FakeVisualAssetService(grouped_assets)
    audio_service = FakeAudioService(None)
    subtitle_service = FakeSubtitleService(None)

    manifest = await service.build_render_manifest(
        run_id=1,
        visual_asset_service=visual_service,
        audio_service=audio_service,
        subtitle_service=subtitle_service,
        render_profile_name="high_quality",
    )

    assert manifest["render_profile"]["name"] == "high_quality"
    assert manifest["render_profile"]["crf"] == 18
    assert manifest["render_profile"]["preset"] == "slow"


@pytest.mark.asyncio
async def test_build_render_manifest_fast_preview_profile() -> None:
    """Test build_render_manifest with fast_preview profile."""
    service = RenderService()

    grouped_assets = {
        "scene_1": [
            FakeVisualAsset(
                scene_id="scene_1",
                asset_path="/asset.png",
                prompt_snapshot="test",
                is_active=True,
            ),
        ],
    }

    visual_service = FakeVisualAssetService(grouped_assets)
    audio_service = FakeAudioService(None)
    subtitle_service = FakeSubtitleService(None)

    manifest = await service.build_render_manifest(
        run_id=1,
        visual_asset_service=visual_service,
        audio_service=audio_service,
        subtitle_service=subtitle_service,
        render_profile_name="fast_preview",
    )

    assert manifest["render_profile"]["name"] == "fast_preview"
    assert manifest["render_profile"]["width"] == 540
    assert manifest["render_profile"]["height"] == 960
    assert manifest["render_profile"]["fps"] == 15
    assert manifest["render_profile"]["crf"] == 28
    assert manifest["render_profile"]["preset"] == "ultrafast"
