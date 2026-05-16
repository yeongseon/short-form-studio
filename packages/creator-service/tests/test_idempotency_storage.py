from __future__ import annotations

import asyncio
import json

from creator_service.audio_service import AudioService, InMemoryAudioStorage
from creator_service.render_service import InMemoryRenderStorage, RenderService
from creator_service.script_service import InMemoryScriptStorage, ScriptService
from creator_service.subtitle_service import InMemorySubtitleStorage, SubtitleService
from creator_service.usage_service import InMemoryUsageStorage, UsageService
from creator_service.visual_asset_service import InMemoryVisualAssetStorage, VisualAssetService
from creator_service.visual_plan_service import InMemoryVisualPlanStorage


def run(coro):
    return asyncio.run(coro)


def test_audio_storage_dedup_by_idempotency_key() -> None:
    service = AudioService(InMemoryAudioStorage())

    first = run(service.create_artifact(1, "/a.wav", idempotency_key="task-1"))
    second = run(service.create_artifact(1, "/b.wav", idempotency_key="task-1"))

    assert first.id == second.id
    assert second.path == "/a.wav"
    assert len(run(service.list_by_run(1))) == 1


def test_audio_storage_no_dedup_without_key() -> None:
    service = AudioService(InMemoryAudioStorage())
    first = run(service.create_artifact(1, "/a.wav"))
    second = run(service.create_artifact(1, "/b.wav"))

    assert first.id != second.id
    assert len(run(service.list_by_run(1))) == 2


def test_script_storage_dedup_by_idempotency_key() -> None:
    service = ScriptService(InMemoryScriptStorage())

    first = run(service.save_draft(1, "generated_by_model", "v1", idempotency_key="task-1"))
    second = run(service.save_draft(1, "generated_by_model", "v2", idempotency_key="task-1"))

    assert first.id == second.id
    assert first.version == second.version
    assert second.markdown_content == "v1"


def test_subtitle_storage_dedup_by_idempotency_key() -> None:
    service = SubtitleService(InMemorySubtitleStorage())

    first = run(service.create_artifact(1, "/a.srt", idempotency_key="task-1"))
    second = run(service.create_artifact(1, "/b.srt", idempotency_key="task-1"))

    assert first.id == second.id
    assert second.path == "/a.srt"
    assert len(run(service.list_by_run(1))) == 1


def test_visual_plan_storage_dedup_by_idempotency_key() -> None:
    storage = InMemoryVisualPlanStorage()
    row = {
        "run_id": 1,
        "scenes_json": json.dumps(
            [
                {
                    "scene_id": "s1",
                    "section_id": "sec1",
                    "scene_index": 0,
                    "section_type": "hook",
                    "original_text": "hello",
                    "prompt": "p1",
                    "prompt_source": "auto_generated",
                    "prompt_edited": False,
                    "style_tags": [],
                    "mood": None,
                    "composition": None,
                    "latest_asset_id": None,
                    "generation_status": "pending",
                }
            ]
        ),
        "idempotency_key": "task-1",
    }

    first = run(storage.save_plan(row))
    second = run(storage.save_plan(row))

    assert first["id"] == second["id"]
    assert first["version"] == second["version"]


def test_visual_asset_storage_dedup_by_idempotency_key() -> None:
    service = VisualAssetService(InMemoryVisualAssetStorage())

    first = run(service.create_asset(1, "scene-1", "/a.png", idempotency_key="task-1:scene-1"))
    second = run(service.create_asset(1, "scene-1", "/b.png", idempotency_key="task-1:scene-1"))

    assert first.id == second.id
    assert first.version == second.version
    assert second.asset_path == "/a.png"


def test_render_storage_dedup_by_idempotency_key() -> None:
    service = RenderService(InMemoryRenderStorage())

    first = run(service.create_artifact(1, "/a.mp4", idempotency_key="task-1"))
    second = run(service.create_artifact(1, "/b.mp4", idempotency_key="task-1"))

    assert first.id == second.id
    assert second.path == "/a.mp4"
    assert len(run(service.list_by_run(1))) == 1


def test_usage_storage_dedup_by_idempotency_key() -> None:
    service = UsageService(InMemoryUsageStorage())

    first = run(
        service.record_usage(
            workspace_id=1,
            run_id=1,
            provider="openai",
            model_key="gpt",
            operation_type="llm",
            estimated_cost_usd=0.1,
            idempotency_key="task-1",
        )
    )
    second = run(
        service.record_usage(
            workspace_id=1,
            run_id=1,
            provider="openai",
            model_key="gpt",
            operation_type="llm",
            estimated_cost_usd=0.2,
            idempotency_key="task-1",
        )
    )

    assert first.id == second.id
    events = run(service.storage.list_by_run(1, workspace_id=1))
    assert len(events) == 1


# --- Postgres backend idempotency tests (unit tests via mocking fetch_one) ---

from unittest.mock import AsyncMock, patch


def test_postgres_audio_storage_uses_idempotency_key() -> None:
    """Postgres audio storage passes idempotency_key to INSERT query."""
    from creator_service.postgres_audio_storage import PostgresAudioStorage

    storage = PostgresAudioStorage()

    async def _test() -> None:
        mock_fetch = AsyncMock(return_value={"id": 1, "run_id": 1, "idempotency_key": "k1"})
        with patch("creator_service.postgres_audio_storage.fetch_one", mock_fetch):
            await storage.save_artifact(
                {"run_id": 1, "file_path": "/a.mp3", "idempotency_key": "k1"}
            )
        call_args = mock_fetch.call_args
        sql = call_args[0][0]
        assert "idempotency_key" in sql
        assert "ON CONFLICT" in sql or "idempotency_key" in sql

    run(_test())


def test_postgres_script_storage_uses_idempotency_key() -> None:
    from creator_service.postgres_script_storage import PostgresScriptStorage

    storage = PostgresScriptStorage()

    async def _test() -> None:
        mock_fetch = AsyncMock(return_value={"id": 1, "run_id": 1, "idempotency_key": "k1"})
        with patch("creator_service.postgres_script_storage.fetch_one", mock_fetch):
            await storage.save_draft(
                {"run_id": 1, "source_type": "llm", "idempotency_key": "k1"}
            )
        sql = mock_fetch.call_args[0][0]
        assert "idempotency_key" in sql

    run(_test())


def test_postgres_render_storage_uses_idempotency_key() -> None:
    from creator_service.postgres_render_storage import PostgresRenderStorage

    storage = PostgresRenderStorage()

    async def _test() -> None:
        mock_fetch = AsyncMock(return_value={"id": 1, "run_id": 1, "idempotency_key": "k1"})
        with patch("creator_service.postgres_render_storage.fetch_one", mock_fetch):
            await storage.save_artifact(
                {"run_id": 1, "file_path": "/v.mp4", "idempotency_key": "k1"}
            )
        sql = mock_fetch.call_args[0][0]
        assert "idempotency_key" in sql

    run(_test())


def test_postgres_usage_storage_uses_idempotency_key() -> None:
    from creator_service.postgres_usage_storage import PostgresUsageStorage

    storage = PostgresUsageStorage()

    async def _test() -> None:
        mock_fetch = AsyncMock(return_value={"id": 1, "run_id": 1, "idempotency_key": "k1"})
        with patch("creator_service.postgres_usage_storage.fetch_one", mock_fetch):
            await storage.record_event(
                {"run_id": 1, "provider": "test", "idempotency_key": "k1"}
            )
        sql = mock_fetch.call_args[0][0]
        assert "idempotency_key" in sql

    run(_test())


def test_postgres_task_tracking_update_guards_success() -> None:
    """Postgres task tracking update_task_status includes status != 'success' guard."""
    from creator_service.postgres_task_tracking_storage import PostgresTaskTrackingStorage

    storage = PostgresTaskTrackingStorage()

    async def _test() -> None:
        # If task is already success, update_task_status returns None
        mock_fetch = AsyncMock(return_value=None)
        with patch("creator_service.postgres_task_tracking_storage.fetch_one", mock_fetch):
            result = await storage.update_task_status(1, "running")
        assert result is None
        sql = mock_fetch.call_args[0][0]
        assert "status != 'success'" in sql

    run(_test())
