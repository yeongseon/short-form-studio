from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_artifact_file_serving_reads_from_storage_backend(client, monkeypatch):
    payload = b"binary-artifact-content"

    def _read_artifact_bytes(path: str) -> bytes:
        assert path == "run-1/render/output.mp4"
        return payload

    monkeypatch.setattr("shorts_api.main.read_artifact_bytes", _read_artifact_bytes)

    response = await client.get("/api/artifacts/files/run-1/render/output.mp4")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"].startswith("video/mp4")


@pytest.mark.asyncio
async def test_artifact_file_serving_returns_404_when_storage_misses(client, monkeypatch):
    def _read_artifact_bytes(_path: str) -> bytes:
        raise FileNotFoundError

    monkeypatch.setattr("shorts_api.main.read_artifact_bytes", _read_artifact_bytes)

    response = await client.get("/api/artifacts/files/missing/path.bin")

    assert response.status_code == 404
    assert response.json() == {"detail": "Artifact not found"}


@pytest.mark.asyncio
async def test_legacy_artifact_route_reads_from_storage_backend(client, monkeypatch):
    payload = b"legacy-route-content"

    def _read_artifact_bytes(path: str) -> bytes:
        assert path == "run-2/render/final.png"
        return payload

    monkeypatch.setattr("shorts_api.main.read_artifact_bytes", _read_artifact_bytes)

    response = await client.get("/artifacts/run-2/render/final.png")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"].startswith("image/png")
    assert "deprecated" in response.headers["warning"].lower()


@pytest.mark.asyncio
async def test_artifact_file_serving_returns_500_when_storage_fails(client, monkeypatch):
    def _read_artifact_bytes(_path: str) -> bytes:
        raise RuntimeError("storage backend unavailable")

    monkeypatch.setattr("shorts_api.main.read_artifact_bytes", _read_artifact_bytes)

    response = await client.get("/api/artifacts/files/run-9/render/output.mp4")

    assert response.status_code == 500
    assert response.json() == {"detail": "Artifact read failed"}
