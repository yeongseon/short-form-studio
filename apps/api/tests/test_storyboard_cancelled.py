"""Tests that storyboard paragraph endpoints reject cancelled runs with 409."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from shorts_api.auth import require_run_access, CurrentUser
from shorts_api.main import app
from shorts_api.routes import creator_runs_storyboard, storyboard_dispatch


def _make_cancelled_run() -> Any:
    return SimpleNamespace(
        id=1,
        status="cancelled",
        current_stage="VISUAL_ASSET_REVIEW",
        project_id=1,
    )


def _install_cancelled_override() -> None:
    run = _make_cancelled_run()

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, Any]:
        _ = run_id
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access


def _remove_run_access_override() -> None:
    app.dependency_overrides.pop(require_run_access, None)


@pytest.mark.asyncio
async def test_generate_paragraph_audio_rejects_cancelled_run(client: Any) -> None:
    _install_cancelled_override()
    try:
        resp = await client.post(
            "/api/creator/runs/1/storyboard/paragraphs/sec-1/generate-audio",
            json={"tts_model": "qwen3-tts", "voice": "default"},
        )
        assert resp.status_code == 409
        assert "cancelled" in resp.json()["detail"].lower()
    finally:
        _remove_run_access_override()


@pytest.mark.asyncio
async def test_generate_paragraph_subtitles_rejects_cancelled_run(client: Any) -> None:
    _install_cancelled_override()
    try:
        resp = await client.post(
            "/api/creator/runs/1/storyboard/paragraphs/sec-1/generate-subtitles",
            json={"subtitle_model": "whisper-small", "subtitle_format": "srt"},
        )
        assert resp.status_code == 409
        assert "cancelled" in resp.json()["detail"].lower()
    finally:
        _remove_run_access_override()


@pytest.mark.asyncio
async def test_generate_all_paragraph_audio_rejects_cancelled_run(client: Any) -> None:
    _install_cancelled_override()
    try:
        resp = await client.post(
            "/api/creator/runs/1/storyboard/generate-all-audio",
            json={"tts_model": "qwen3-tts", "voice": "default"},
        )
        assert resp.status_code == 409
        assert "cancelled" in resp.json()["detail"].lower()
    finally:
        _remove_run_access_override()


@pytest.mark.asyncio
async def test_generate_all_paragraph_subtitles_rejects_cancelled_run(client: Any) -> None:
    _install_cancelled_override()
    try:
        resp = await client.post(
            "/api/creator/runs/1/storyboard/generate-all-subtitles",
            json={"subtitle_model": "whisper-small", "subtitle_format": "srt"},
        )
        assert resp.status_code == 409
        assert "cancelled" in resp.json()["detail"].lower()
    finally:
        _remove_run_access_override()


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
        _ = run_id
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    async def _mock_get_active_draft(_run_id: int) -> Any:
        return SimpleNamespace(
            structured_script=[SimpleNamespace(section_id="sec-1", text="hello")]
        )

    async def _mock_check_workspace_quota(
        _workspace_id: int, operation_type: str
    ) -> tuple[bool, str]:
        _ = operation_type
        return True, "ok"

    async def _mock_get_run(_run_id: int, workspace_id: int | None = None) -> Any:
        _ = workspace_id
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
    monkeypatch.setattr("creator_service.run_service.run_service.get_run", _mock_get_run)

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
        _ = run_id
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    async def _mock_get_active_draft(_run_id: int) -> Any:
        return SimpleNamespace(
            structured_script=[SimpleNamespace(section_id="sec-1", text="hello")]
        )

    async def _mock_check_workspace_quota(
        _workspace_id: int, operation_type: str
    ) -> tuple[bool, str]:
        _ = operation_type
        return True, "ok"

    async def _mock_get_run(_run_id: int, workspace_id: int | None = None) -> Any:
        _ = workspace_id
        return SimpleNamespace(id=1, status="running", current_stage="VISUAL_ASSET_REVIEW")

    async def _mock_record_task_queued(_run_id: int, _task_name: str, _task_id: str) -> None:
        raise RuntimeError("db failure")

    revoke_calls: list[tuple[str, bool]] = []
    mark_tasks_revoked_calls: list[list[str]] = []
    celery_app = SimpleNamespace(
        control=SimpleNamespace(
            revoke=lambda task_id, terminate=False: revoke_calls.append((task_id, terminate))
        )
    )

    async def _mock_mark_tasks_revoked(task_ids: list[str]) -> None:
        mark_tasks_revoked_calls.append(task_ids)

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
    monkeypatch.setattr("creator_service.run_service.run_service.get_run", _mock_get_run)
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.dispatch_paragraph_audio",
        lambda **kwargs: "task-123",
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch.task_tracking_service.record_task_queued",
        _mock_record_task_queued,
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch.task_tracking_service.mark_tasks_revoked",
        _mock_mark_tasks_revoked,
    )
    monkeypatch.setattr(
        storyboard_dispatch,
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
        assert mark_tasks_revoked_calls == [["task-123"]]
    finally:
        app.dependency_overrides.pop(require_run_access, None)


@pytest.mark.asyncio
async def test_post_dispatch_revoke_on_concurrent_cancellation(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = SimpleNamespace(
        id=1,
        status="running",
        current_stage="VISUAL_ASSET_REVIEW",
        project_id=1,
    )

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, Any]:
        _ = run_id
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    async def _mock_get_active_draft(_run_id: int) -> Any:
        return SimpleNamespace(
            structured_script=[SimpleNamespace(section_id="sec-1", text="hello")]
        )

    async def _mock_check_workspace_quota(
        _workspace_id: int, operation_type: str
    ) -> tuple[bool, str]:
        _ = operation_type
        return True, "ok"

    async def _mock_cancel_workspace_quota_reservation(
        _workspace_id: int, operation_type: str
    ) -> None:
        _ = operation_type
        return None

    states = [
        SimpleNamespace(id=1, status="running", current_stage="VISUAL_ASSET_REVIEW"),
        SimpleNamespace(id=1, status="cancelled", current_stage="VISUAL_ASSET_REVIEW"),
    ]

    async def _mock_get_fresh_run_for_dispatch(_run_id: int, _workspace_id: int) -> Any:
        return states.pop(0)

    async def _mock_record_task_queued(_run_id: int, _task_name: str, _task_id: str) -> None:
        return None

    revoke_calls: list[tuple[str, bool]] = []
    mark_tasks_revoked_calls: list[list[str]] = []
    celery_app = SimpleNamespace(
        control=SimpleNamespace(
            revoke=lambda task_id, terminate=False: revoke_calls.append((task_id, terminate))
        )
    )

    async def _mock_mark_tasks_revoked(task_ids: list[str]) -> None:
        mark_tasks_revoked_calls.append(task_ids)

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
        "shorts_api.routes.storyboard_dispatch.cancel_workspace_quota_reservation",
        _mock_cancel_workspace_quota_reservation,
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch._get_fresh_run_for_dispatch",
        _mock_get_fresh_run_for_dispatch,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.dispatch_paragraph_audio",
        lambda **kwargs: "task-123",
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch.task_tracking_service.record_task_queued",
        _mock_record_task_queued,
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch.task_tracking_service.mark_tasks_revoked",
        _mock_mark_tasks_revoked,
    )
    monkeypatch.setattr(
        storyboard_dispatch,
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
        assert resp.status_code == 409
        assert revoke_calls == [("task-123", True)]
        assert mark_tasks_revoked_calls == [["task-123"]]
    finally:
        app.dependency_overrides.pop(require_run_access, None)


@pytest.mark.asyncio
async def test_bulk_audio_post_dispatch_revoke_on_concurrent_cancellation(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that mark_tasks_revoked is called when bulk audio dispatch faces concurrent cancellation."""
    run = SimpleNamespace(
        id=1,
        status="running",
        current_stage="VISUAL_ASSET_REVIEW",
        project_id=1,
    )

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, Any]:
        _ = run_id
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    async def _mock_get_active_draft(_run_id: int) -> Any:
        section = SimpleNamespace(
            section_id="sec-1",
            text="Hello",
            display_text="Hello",
            type="narration",
            speaker=None,
            duration=None,
            turn_kind=None,
            visual_override=None,
            image_prompt=None,
        )
        return SimpleNamespace(structured_script=[section])

    async def _mock_check_workspace_quota(
        _workspace_id: int, operation_type: str
    ) -> tuple[bool, str]:
        _ = operation_type
        return True, "ok"

    async def _mock_cancel_workspace_quota_reservation(
        _workspace_id: int, operation_type: str
    ) -> None:
        _ = operation_type
        return None

    states = [
        SimpleNamespace(id=1, status="running", current_stage="VISUAL_ASSET_REVIEW"),
        SimpleNamespace(id=1, status="cancelled", current_stage="VISUAL_ASSET_REVIEW"),
    ]

    async def _mock_get_fresh_run_for_dispatch(_run_id: int, _workspace_id: int) -> Any:
        return states.pop(0)

    async def _mock_list_paragraph_audio(_run_id: int) -> list:
        return []

    async def _mock_record_task_queued(_run_id: int, _task_name: str, _task_id: str) -> None:
        return None

    revoke_calls: list[str] = []
    mark_tasks_revoked_calls: list[list[str]] = []
    celery_app = SimpleNamespace(
        control=SimpleNamespace(
            revoke=lambda task_id, terminate=False: revoke_calls.append(task_id)
        )
    )

    async def _mock_mark_tasks_revoked(task_ids: list[str]) -> None:
        mark_tasks_revoked_calls.append(task_ids)

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
        "shorts_api.routes.storyboard_dispatch.cancel_workspace_quota_reservation",
        _mock_cancel_workspace_quota_reservation,
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch._get_fresh_run_for_dispatch",
        _mock_get_fresh_run_for_dispatch,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.audio_service.list_paragraph_audio",
        _mock_list_paragraph_audio,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.dispatch_paragraph_audio",
        lambda **kwargs: "bulk-task-1",
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch.task_tracking_service.record_task_queued",
        _mock_record_task_queued,
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch.task_tracking_service.mark_tasks_revoked",
        _mock_mark_tasks_revoked,
    )
    monkeypatch.setattr(
        storyboard_dispatch,
        "__import__",
        lambda name: SimpleNamespace(celery_app=celery_app)
        if name == "celery_app"
        else __import__(name),
        raising=False,
    )

    try:
        resp = await client.post(
            "/api/creator/runs/1/storyboard/generate-all-audio",
            json={"tts_model": "qwen3-tts", "voice": "default"},
        )
        assert resp.status_code == 409
        assert revoke_calls == ["bulk-task-1"]
        assert mark_tasks_revoked_calls == [["bulk-task-1"]]
    finally:
        app.dependency_overrides.pop(require_run_access, None)


@pytest.mark.asyncio
async def test_bulk_subtitles_record_failure_revokes_task(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that mark_tasks_revoked is called when bulk subtitles dispatch faces record_task_queued failure."""
    run = SimpleNamespace(
        id=1,
        status="running",
        current_stage="VISUAL_ASSET_REVIEW",
        project_id=1,
    )

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, Any]:
        _ = run_id
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    async def _mock_get_active_draft(_run_id: int) -> Any:
        section = SimpleNamespace(
            section_id="sec-1",
            text="Hello",
            display_text="Hello",
            type="narration",
            speaker=None,
            duration=None,
            turn_kind=None,
            visual_override=None,
            image_prompt=None,
        )
        return SimpleNamespace(structured_script=[section])

    async def _mock_check_workspace_quota(
        _workspace_id: int, operation_type: str
    ) -> tuple[bool, str]:
        _ = operation_type
        return True, "ok"

    async def _mock_cancel_workspace_quota_reservation(
        _workspace_id: int, operation_type: str
    ) -> None:
        _ = operation_type
        return None

    async def _mock_get_fresh_run_for_dispatch(_run_id: int, _workspace_id: int) -> Any:
        return SimpleNamespace(id=1, status="running", current_stage="VISUAL_ASSET_REVIEW")

    async def _mock_list_paragraph_audio(_run_id: int) -> list:
        audio = SimpleNamespace(section_id="sec-1", path="/audio.mp3", id=1)
        return [audio]

    async def _mock_list_paragraph_subtitles(_run_id: int) -> list:
        return []

    async def _mock_record_task_queued(_run_id: int, _task_name: str, _task_id: str) -> None:
        raise RuntimeError("db failure")

    revoke_calls: list[str] = []
    mark_tasks_revoked_calls: list[list[str]] = []
    celery_app = SimpleNamespace(
        control=SimpleNamespace(
            revoke=lambda task_id, terminate=False: revoke_calls.append(task_id)
        )
    )

    async def _mock_mark_tasks_revoked(task_ids: list[str]) -> None:
        mark_tasks_revoked_calls.append(task_ids)

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
        "shorts_api.routes.storyboard_dispatch.cancel_workspace_quota_reservation",
        _mock_cancel_workspace_quota_reservation,
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch._get_fresh_run_for_dispatch",
        _mock_get_fresh_run_for_dispatch,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.audio_service.list_paragraph_audio",
        _mock_list_paragraph_audio,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.subtitle_service.list_paragraph_subtitles",
        _mock_list_paragraph_subtitles,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.dispatch_paragraph_subtitles",
        lambda **kwargs: "sub-task-1",
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch.task_tracking_service.record_task_queued",
        _mock_record_task_queued,
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch.task_tracking_service.mark_tasks_revoked",
        _mock_mark_tasks_revoked,
    )
    monkeypatch.setattr(
        storyboard_dispatch,
        "__import__",
        lambda name: SimpleNamespace(celery_app=celery_app)
        if name == "celery_app"
        else __import__(name),
        raising=False,
    )

    try:
        resp = await client.post(
            "/api/creator/runs/1/storyboard/generate-all-subtitles",
            json={"subtitle_model": "whisper-small", "subtitle_format": "srt"},
        )
        # Bulk endpoints catch exceptions and append error entries
        data = resp.json()
        assert resp.status_code == 202
        assert data["failed"] >= 1
        assert any(t.get("error") == "dispatch_failed" for t in data["tasks"])
        assert revoke_calls == ["sub-task-1"]
        assert mark_tasks_revoked_calls == [["sub-task-1"]]
    finally:
        app.dependency_overrides.pop(require_run_access, None)


# --- Tests for _get_fresh_run_for_dispatch fail-closed on exceptions ---


@pytest.mark.asyncio
async def test_get_fresh_run_for_dispatch_returns_none_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_fresh_run_for_dispatch returns None when get_run raises, enabling fail-closed."""
    async def _raise(_run_id: int, **kwargs: Any) -> None:
        raise RuntimeError("DB connection lost")

    monkeypatch.setattr(
        "creator_service.run_service.run_service.get_run",
        _raise,
    )
    result = await storyboard_dispatch._get_fresh_run_for_dispatch(1, 1)
    assert result is None


@pytest.mark.asyncio
async def test_pre_dispatch_reread_exception_fails_closed(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When run_service.get_run raises during pre-dispatch re-read, endpoint returns 409 (fail-closed via None)."""
    run = SimpleNamespace(
        id=1, status="running", current_stage="VISUAL_ASSET_REVIEW", project_id=1
    )

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, Any]:
        _ = run_id
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    async def _mock_get_active_draft(_run_id: int) -> Any:
        return SimpleNamespace(
            structured_script=[SimpleNamespace(section_id="sec-1", text="hello")]
        )

    async def _mock_check_workspace_quota(
        _workspace_id: int, operation_type: str
    ) -> tuple[bool, str]:
        _ = operation_type
        return True, "ok"

    cancel_quota_calls: list[str] = []

    async def _mock_cancel_quota(_workspace_id: int, operation_type: str) -> None:
        cancel_quota_calls.append(operation_type)

    # Make run_service.get_run raise — exercises the real _get_fresh_run_for_dispatch wrapper
    async def _raising_get_run(_run_id: int, **kwargs: Any) -> None:
        raise RuntimeError("DB connection lost")

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
        "shorts_api.routes.storyboard_dispatch.cancel_workspace_quota_reservation",
        _mock_cancel_quota,
    )
    monkeypatch.setattr(
        "creator_service.run_service.run_service.get_run",
        _raising_get_run,
    )

    try:
        resp = await client.post(
            "/api/creator/runs/1/storyboard/paragraphs/sec-1/generate-audio",
            json={"tts_model": "qwen3-tts", "voice": "default"},
        )
        # _get_fresh_run_for_dispatch catches exception → returns None → 409 + quota cancel
        assert resp.status_code == 409
        assert "cancelled" in resp.json()["detail"].lower()
        assert cancel_quota_calls == ["tts"]
    finally:
        app.dependency_overrides.pop(require_run_access, None)


@pytest.mark.asyncio
async def test_post_dispatch_reread_exception_revokes_task(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When run_service.get_run raises during post-dispatch re-read, task is revoked (fail-closed)."""
    run = SimpleNamespace(
        id=1, status="running", current_stage="VISUAL_ASSET_REVIEW", project_id=1
    )

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, Any]:
        _ = run_id
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    async def _mock_get_active_draft(_run_id: int) -> Any:
        return SimpleNamespace(
            structured_script=[SimpleNamespace(section_id="sec-1", text="hello")]
        )

    async def _mock_check_workspace_quota(
        _workspace_id: int, operation_type: str
    ) -> tuple[bool, str]:
        _ = operation_type
        return True, "ok"

    cancel_quota_calls: list[str] = []

    async def _mock_cancel_quota(_workspace_id: int, operation_type: str) -> None:
        cancel_quota_calls.append(operation_type)

    call_count = 0

    async def _get_run_ok_then_raise(_run_id: int, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Pre-dispatch re-read succeeds
            return SimpleNamespace(id=1, status="running", current_stage="VISUAL_ASSET_REVIEW")
        # Post-dispatch re-read fails
        raise RuntimeError("DB gone during post-dispatch check")

    async def _mock_record_task_queued(_run_id: int, _task_name: str, _task_id: str) -> None:
        return None

    revoke_calls: list[tuple[str, bool]] = []
    mark_tasks_revoked_calls: list[list[str]] = []
    celery_app = SimpleNamespace(
        control=SimpleNamespace(
            revoke=lambda task_id, terminate=False: revoke_calls.append((task_id, terminate))
        )
    )

    async def _mock_mark_tasks_revoked(task_ids: list[str]) -> None:
        mark_tasks_revoked_calls.append(task_ids)

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
        "shorts_api.routes.storyboard_dispatch.cancel_workspace_quota_reservation",
        _mock_cancel_quota,
    )
    monkeypatch.setattr(
        "creator_service.run_service.run_service.get_run",
        _get_run_ok_then_raise,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_storyboard.dispatch_paragraph_audio",
        lambda **kwargs: "task-123",
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch.task_tracking_service.record_task_queued",
        _mock_record_task_queued,
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch.task_tracking_service.mark_tasks_revoked",
        _mock_mark_tasks_revoked,
    )
    monkeypatch.setattr(
        storyboard_dispatch,
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
        # Post-dispatch re-read returns None (exception caught) → treated as cancelled → revoke
        assert resp.status_code == 409
        assert revoke_calls == [("task-123", True)]
        assert mark_tasks_revoked_calls == [["task-123"]]
        assert cancel_quota_calls == ["tts"]
    finally:
        app.dependency_overrides.pop(require_run_access, None)
