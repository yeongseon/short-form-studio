from __future__ import annotations

from pathlib import Path

from creator_service.object_storage import StorageResult


class _MockBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, str]] = []

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
        return f"mock://{key}?expires_in={expires_in}"


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


def test_store_artifact_file_returns_none_on_upload_failure(tmp_path, monkeypatch):
    from creator_service import artifact_storage_integration as mod

    run_id = 7
    artifact_root = tmp_path / "artifacts"
    local_path = artifact_root / str(run_id) / "audio" / "audio.wav"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(b"audio-bytes")

    class _FailingBackend:
        def upload(
            self, key: str, data: bytes, content_type: str = "application/octet-stream"
        ) -> StorageResult:
            raise RuntimeError("upload failed")

    monkeypatch.setattr(mod, "_ARTIFACT_ROOT", artifact_root.resolve())
    monkeypatch.setattr(mod, "get_storage_backend", lambda: _FailingBackend())

    result = mod.store_artifact_file(run_id, local_path, "audio/wav")

    assert result is None


def test_get_artifact_url_delegates_to_backend(monkeypatch):
    from creator_service import artifact_storage_integration as mod

    backend = _MockBackend()
    monkeypatch.setattr(mod, "get_storage_backend", lambda: backend)

    url = mod.get_artifact_url("10/scenes/scene-1.png", expires_in=120)

    assert url == "mock://10/scenes/scene-1.png?expires_in=120"
