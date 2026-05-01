from __future__ import annotations

import pytest
from creator_service.audio_service import AudioService, InMemoryAudioStorage
from creator_service.render_service import InMemoryRenderStorage, RenderService
from creator_service.subtitle_service import InMemorySubtitleStorage, SubtitleService


@pytest.mark.asyncio
async def test_audio_artifact_persists_storage_metadata():
    storage = InMemoryAudioStorage()
    service = AudioService(storage)

    artifact = await service.create_artifact(
        run_id=1,
        path="data/artifacts/1/audio/audio.wav",
        storage_provider="s3",
        storage_key="1/audio/audio.wav",
    )

    assert artifact.path == "data/artifacts/1/audio/audio.wav"
    metadata = storage._artifacts[0]["metadata_json"]
    assert metadata["storage_provider"] == "s3"
    assert metadata["storage_key"] == "1/audio/audio.wav"


@pytest.mark.asyncio
async def test_subtitle_artifact_persists_storage_metadata():
    storage = InMemorySubtitleStorage()
    service = SubtitleService(storage)

    artifact = await service.create_artifact(
        run_id=2,
        path="data/artifacts/2/subtitles/subtitles.srt",
        storage_provider="azure_blob",
        storage_key="2/subtitles/subtitles.srt",
    )

    assert artifact.path == "data/artifacts/2/subtitles/subtitles.srt"
    metadata = storage._artifacts[0]["metadata_json"]
    assert metadata["storage_provider"] == "azure_blob"
    assert metadata["storage_key"] == "2/subtitles/subtitles.srt"


@pytest.mark.asyncio
async def test_render_artifact_persists_storage_metadata():
    storage = InMemoryRenderStorage()
    service = RenderService(storage)

    artifact = await service.create_artifact(
        run_id=3,
        path="data/artifacts/3/render/output.mp4",
        storage_provider="gcs",
        storage_key="3/render/output.mp4",
    )

    assert artifact.path == "data/artifacts/3/render/output.mp4"
    metadata = storage._artifacts[0]["metadata_json"]
    assert metadata["storage_provider"] == "gcs"
    assert metadata["storage_key"] == "3/render/output.mp4"
