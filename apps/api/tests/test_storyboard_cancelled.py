"""Tests that storyboard paragraph endpoints reject cancelled runs with 409."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from shorts_api.auth import require_run_access, CurrentUser
from shorts_api.main import app
from shorts_api.routes import creator_runs_storyboard


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


@pytest.mark.asyncio
async def test_dispatch_blocked_on_concurrent_cancellation(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = SimpleNamespace(
        id=1,
        status="running",
        current_stage="VISUAL_ASSET_REVIEW",
        project_id=1,
    )

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, Any]:
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    async def _mock_get_active_draft(_run_id: int) -> Any:
        return SimpleNamespace(
            structured_script=[SimpleNamespace(section_id="sec-1", text="hello")]
        )

    async def _mock_check_workspace_quota(
        _workspace_id: int, operation_type: str
    ) -> tuple[bool, str]:
        return True, "ok"

    async def _mock_get_run(_run_id: int, workspace_id: int) -> Any:
        return SimpleNamespace(id=1, status="cancelled", current_stage="VISUAL_ASSET_REVIEW")

    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.script_service.get_active_draft",
        _mock_get_active_draft,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.validate_model_key",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.check_workspace_quota",
        _mock_check_workspace_quota,
    )
    monkeypatch.setattr(
        creator_runs_storyboard,
        "run_service",
        SimpleNamespace(get_run=_mock_get_run),
        raising=False,
    )

    try:
        resp = await client.post(
            "/api/creator/runs/1/storyboard/paragraphs/sec-1/generate-audio",
            json={"tts_model": "qwen3-tts", "voice": "default"},
        )
        assert resp.status_code == 409
        assert "cancelled" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(require_run_access, None)


@pytest.mark.asyncio
async def test_record_task_queued_failure_revokes_task(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = SimpleNamespace(
        id=1,
        status="running",
        current_stage="VISUAL_ASSET_REVIEW",
        project_id=1,
    )

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, Any]:
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    async def _mock_get_active_draft(_run_id: int) -> Any:
        return SimpleNamespace(
            structured_script=[SimpleNamespace(section_id="sec-1", text="hello")]
        )

    async def _mock_check_workspace_quota(
        _workspace_id: int, operation_type: str
    ) -> tuple[bool, str]:
        return True, "ok"

    async def _mock_get_run(_run_id: int, workspace_id: int) -> Any:
        return SimpleNamespace(id=1, status="running", current_stage="VISUAL_ASSET_REVIEW")

    async def _mock_record_task_queued(_run_id: int, _task_name: str, _task_id: str) -> None:
        raise RuntimeError("db failure")

    revoke_calls: list[tuple[str, bool]] = []
    celery_app = SimpleNamespace(
        control=SimpleNamespace(
            revoke=lambda task_id, terminate=False: revoke_calls.append((task_id, terminate))
        )
    )

    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.script_service.get_active_draft",
        _mock_get_active_draft,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.validate_model_key",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.check_workspace_quota",
        _mock_check_workspace_quota,
    )
    monkeypatch.setattr(
        creator_runs_storyboard,
        "run_service",
        SimpleNamespace(get_run=_mock_get_run),
        raising=False,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.dispatch_paragraph_audio",
        lambda **kwargs: "task-123",
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.task_tracking_service.record_task_queued",
        _mock_record_task_queued,
    )
    monkeypatch.setattr(
        creator_runs_storyboard,
        "__import__",
        lambda name: SimpleNamespace(celery_app=celery_app)
        if name == "celery_app"
        else __import__(name),
        raising=False,
    )

    try:
        resp = await client.post(
            "/api/creator/runs/1/storyboard/paragraphs/sec-1/generate-audio",
            json={"tts_model": "qwen3-tts", "voice": "default"},
        )
        assert resp.status_code == 503
        assert revoke_calls == [("task-123", True)]
    finally:
        app.dependency_overrides.pop(require_run_access, None)
