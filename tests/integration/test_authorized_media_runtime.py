"""Opt-in checks against a real nginx/API fixture provisioned with owned media."""

import os
from pathlib import Path

import httpx
import pytest


def test_nginx_serves_authorized_media_bytes():
    base = os.getenv("MEDIA_TEST_URL")
    artifact_root = os.getenv("MEDIA_TEST_ARTIFACT_ROOT")
    if not base or not artifact_root:
        pytest.skip("A provisioned nginx/API media fixture is required")
    cases = [
        ("/api/creator/runs/1/visual-assets/1/content", "scene.png", "image/png"),
        ("/api/creator/runs/1/artifacts/1/download", "audio.wav", "audio/wav"),
        ("/api/creator/runs/1/artifacts/2/download", "captions.srt", "application/x-subrip"),
        ("/api/creator/runs/1/artifacts/3/download", "video.mp4", "video/mp4"),
        ("/api/creator/workspaces/1/assets/1/content", "scene.png", "image/png"),
        ("/api/creator/workspaces/1/assets/2/content", "video.mp4", "video/mp4"),
    ]
    with httpx.Client(base_url=base, timeout=10) as client:
        for url, filename, mime in cases:
            response = client.get(url)
            assert response.status_code == 200, (url, response.text)
            assert response.headers["content-type"] == mime
            assert response.content == (Path(artifact_root) / filename).read_bytes()
            assert set(response.headers.get_list("x-content-type-options")) == {"nosniff"}
            if url.endswith("/download"):
                assert response.headers["content-disposition"].startswith("attachment;")
        assert client.get("/api/artifacts/files/1/scene.png").status_code == 404
        for url in ["/api/creator/runs/999/visual-assets/1/content", "/api/creator/runs/1/visual-assets/999/content", "/api/creator/workspaces/999/assets/1/content", "/api/creator/workspaces/1/assets/999/content"]:
            assert client.get(url).status_code == 404
        assert client.post("/api/creator/demo", headers={"Origin": "https://foreign.invalid"}).status_code == 403


def test_media_api_rejects_anonymous_and_foreign_identity():
    base = os.getenv("MEDIA_TEST_API_URL")
    foreign_key = os.getenv("MEDIA_TEST_FOREIGN_KEY")
    if not base or not foreign_key:
        pytest.skip("A provisioned API with a foreign identity is required")
    with httpx.Client(base_url=base, timeout=10) as client:
        for url in ["/api/creator/runs/1/visual-assets/1/content", "/api/creator/runs/1/artifacts/1/download", "/api/creator/workspaces/1/assets/1/content"]:
            assert client.get(url).status_code == 401
            assert client.get(url, headers={"X-API-Key": foreign_key}).status_code == 404
