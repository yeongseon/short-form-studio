from io import BytesIO
from threading import get_ident
import wave

import pytest
from creator_service import media_probe
from creator_service.media_asset_service import MediaAssetService
from creator_service.media_asset_storage import InMemoryMediaAssetStorage
from creator_service.object_storage import LocalStorageBackend


@pytest.mark.asyncio
async def test_real_ffprobe_and_filesystem_upload_execute_off_loop(monkeypatch, tmp_path):
    payload = BytesIO()
    with wave.open(payload, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000)
    loop_thread = get_ident()
    threads = []
    original = media_probe.subprocess.run

    def probe(*args, **kwargs):
        threads.append(get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(media_probe.subprocess, "run", probe)
    backend = LocalStorageBackend(str(tmp_path))
    service = MediaAssetService(backend, InMemoryMediaAssetStorage())
    asset = await service.create_audio_asset(workspace_id=1, filename="tone.wav", data=payload.getvalue(), content_type="audio/wav")
    assert asset.duration_seconds == pytest.approx(1.0)
    assert threads and all(thread != loop_thread for thread in threads)
    assert backend.download_bytes(asset.storage_key) == payload.getvalue()
