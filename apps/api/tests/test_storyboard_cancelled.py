"""Tests that storyboard paragraph endpoints reject cancelled runs with 409."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from shorts_api.auth import require_run_access, CurrentUser
from shorts_api.main import app


def _make_cancelled_run() -> Any:
    return SimpleNamespace(
        id=1,
        status="cancelled",
        current_stage="VISUAL_ASSET_REVIEW",
        project_id=1,
    )


@pytest.fixture()
def _override_cancelled(client: Any) -> Any:  # noqa: ARG001 – client needed for setup order
    run = _make_cancelled_run()

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, Any]:
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access
    yield
    app.dependency_overrides.pop(require_run_access, None)


@pytest.mark.asyncio
async def test_generate_paragraph_audio_rejects_cancelled_run(
    client: Any, _override_cancelled: Any
) -> None:
    resp = await client.post(
        "/api/creator/runs/1/storyboard/paragraphs/sec-1/generate-audio",
        json={"tts_model": "qwen3-tts", "voice": "default"},
    )
    assert resp.status_code == 409
    assert "cancelled" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_paragraph_subtitles_rejects_cancelled_run(
    client: Any, _override_cancelled: Any
) -> None:
    resp = await client.post(
        "/api/creator/runs/1/storyboard/paragraphs/sec-1/generate-subtitles",
        json={"subtitle_model": "whisper-small", "subtitle_format": "srt"},
    )
    assert resp.status_code == 409
    assert "cancelled" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_all_paragraph_audio_rejects_cancelled_run(
    client: Any, _override_cancelled: Any
) -> None:
    resp = await client.post(
        "/api/creator/runs/1/storyboard/generate-all-audio",
        json={"tts_model": "qwen3-tts", "voice": "default"},
    )
    assert resp.status_code == 409
    assert "cancelled" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_all_paragraph_subtitles_rejects_cancelled_run(
    client: Any, _override_cancelled: Any
) -> None:
    resp = await client.post(
        "/api/creator/runs/1/storyboard/generate-all-subtitles",
        json={"subtitle_model": "whisper-small", "subtitle_format": "srt"},
    )
    assert resp.status_code == 409
    assert "cancelled" in resp.json()["detail"].lower()
