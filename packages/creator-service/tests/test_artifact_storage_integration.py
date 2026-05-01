from __future__ import annotations

import pytest
from creator_service.object_storage import StorageResult


class _MockBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, str]] = []
        self.download_byte_calls: list[str] = []
        self.download_url_calls: list[tuple[str, int]] = []

    def upload(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StorageResult:
        self.calls.append((key, data, content_type))
        return StorageResult(
            key=key,
            size_bytes=len(data),
            content_type=content_type,
            checksum="mock-checksum",
            storage_provider="mock",
        )

    def download_url(self, key: str, expires_in: int = 3600) -> str:
        self.download_url_calls.append((key, expires_in))
        return f"mock://{key}?expires_in={expires_in}"

    def download_bytes(self, key: str) -> bytes:
        self.download_byte_calls.append(key)
        return f"bytes:{key}".encode()


def test_store_artifact_file_uploads_relative_key(tmp_path, monkeypatch):
    from creator_service import artifact_storage_integration as mod

    run_id = 42
    artifact_root = tmp_path / "artifacts"
    local_path = artifact_root / str(run_id) / "render" / "output.mp4"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(b"video-bytes")

    backend = _MockBackend()
    monkeypatch.setattr(mod, "_ARTIFACT_ROOT", artifact_root.resolve())
    monkeypatch.setattr(mod, "get_storage_backend", lambda: backend)

    result = mod.store_artifact_file(run_id, local_path, "video/mp4")

    assert result is not None
    assert result.key == "42/render/output.mp4"
    assert backend.calls == [("42/render/output.mp4", b"video-bytes", "video/mp4")]


def test_store_artifact_file_raises_on_upload_failure(tmp_path, monkeypatch):
    from creator_service import artifact_storage_integration as mod

    run_id = 7
    artifact_root = tmp_path / "artifacts"
    local_path = artifact_root / str(run_id) / "audio" / "audio.wav"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(b"audio-bytes")

    class _FailingBackend:
        def upload(
            self,
            _key: str,
            _data: bytes,
            content_type: str = "application/octet-stream",
        ) -> StorageResult:
            _ = content_type
            raise RuntimeError("upload failed")

    monkeypatch.setattr(mod, "_ARTIFACT_ROOT", artifact_root.resolve())
    monkeypatch.setattr(mod, "get_storage_backend", lambda: _FailingBackend())

    with pytest.raises(RuntimeError, match="upload failed"):
        mod.store_artifact_file(run_id, local_path, "audio/wav")


def test_get_artifact_url_delegates_to_backend(monkeypatch):
    from creator_service import artifact_storage_integration as mod

    backend = _MockBackend()
    monkeypatch.setattr(mod, "get_storage_backend", lambda: backend)

    url = mod.get_artifact_url("10/scenes/scene-1.png", expires_in=120)

    assert url == "mock://10/scenes/scene-1.png?expires_in=120"
    assert backend.download_url_calls == [("10/scenes/scene-1.png", 120)]


def test_get_artifact_bytes_delegates_to_backend(monkeypatch):
    from creator_service import artifact_storage_integration as mod

    backend = _MockBackend()
    monkeypatch.setattr(mod, "get_storage_backend", lambda: backend)

    data = mod.get_artifact_bytes("10/scenes/scene-2.png")

    assert data == b"bytes:10/scenes/scene-2.png"
    assert backend.download_byte_calls == ["10/scenes/scene-2.png"]


def test_get_artifact_download_path_delegates_to_backend(monkeypatch):
    from creator_service import artifact_storage_integration as mod

    backend = _MockBackend()
    monkeypatch.setattr(mod, "get_storage_backend", lambda: backend)

    path = mod.get_artifact_download_path("10/scenes/scene-3.png", expires_in=45)

    assert path == "mock://10/scenes/scene-3.png?expires_in=45"
    assert backend.download_url_calls == [("10/scenes/scene-3.png", 45)]
