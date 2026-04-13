"""Shared helpers and task dispatch for creator run routes."""

import json
import logging
from collections.abc import Callable, Mapping
from importlib import import_module
from typing import Any, cast

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def dispatch_generate_script(
    run_id: int, idea_brief: str, model_key: str, instructions: str | None
) -> str:
    """Dispatch generate_script Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.generate_script")
    result = tasks.generate_script.delay(run_id, idea_brief, model_key, instructions)
    return str(result.id)


def dispatch_generate_visual_plan(
    run_id: int, model_key: str, style_preset: str | None
) -> str:
    """Dispatch generate_visual_plan Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.generate_visual_plan")
    result = tasks.generate_visual_plan.delay(run_id, model_key, style_preset)
    return str(result.id)


def dispatch_generate_audio(run_id: int, tts_model: str, voice: str) -> str:
    """Dispatch generate_audio Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.generate_audio")
    result = tasks.generate_audio.delay(run_id, tts_model=tts_model, voice=voice)
    return str(result.id)


def dispatch_generate_subtitles(run_id: int, subtitle_model: str, subtitle_format: str) -> str:
    """Dispatch generate_subtitles Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.generate_subtitles")
    result = tasks.generate_subtitles.delay(run_id, subtitle_model=subtitle_model, subtitle_format=subtitle_format)
    return str(result.id)


def dispatch_render_video(run_id: int, render_profile: str) -> str:
    """Dispatch render_video Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.render_video")
    result = tasks.render_video.delay(run_id, render_profile=render_profile)
    return str(result.id)


def dispatch_generate_scene_image(
    run_id: int,
    model_key: str,
    scene_id: str | None,
    prompt_override: str | None,
    is_active: bool,
    image_params: dict[str, Any] | None = None,
) -> str:
    """Dispatch generate_scene_image Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.generate_scene_image")
    result = tasks.generate_scene_image.delay(
        run_id,
        scene_id=scene_id,
        model_key=model_key,
        prompt_override=prompt_override,
        is_active=is_active,
        image_params=image_params,
    )
    return str(result.id)


def dispatch_paragraph_audio(
    run_id: int, section_id: str, section_text: str, tts_model: str, voice: str
) -> str:
    """Dispatch generate_paragraph_audio Celery task. Returns task id."""
    from importlib import import_module

    tasks = import_module("tasks.generate_paragraph_audio")
    result = tasks.generate_paragraph_audio.delay(
        run_id,
        section_id=section_id,
        section_text=section_text,
        tts_model=tts_model,
        voice=voice,
    )
    return str(result.id)


def dispatch_paragraph_subtitles(
    run_id: int,
    section_id: str,
    audio_path: str,
    subtitle_model: str,
    subtitle_format: str,
) -> str:
    """Dispatch generate_paragraph_subtitles Celery task. Returns task id."""
    from importlib import import_module

    tasks = import_module("tasks.generate_paragraph_subtitles")
    result = tasks.generate_paragraph_subtitles.delay(
        run_id,
        section_id=section_id,
        audio_path=audio_path,
        subtitle_model=subtitle_model,
        subtitle_format=subtitle_format,
    )
    return str(result.id)


def _revoke_active_tasks(active_task_id: str | None) -> None:
    """Revoke all Celery tasks stored in active_task_id (JSON list or legacy single ID)."""
    if not active_task_id:
        return
    try:
        celery_app = __import__("celery_app").celery_app

        # Parse as JSON list; fall back to single ID for backwards compat
        try:
            task_ids = json.loads(active_task_id)
            if isinstance(task_ids, str):
                task_ids = [task_ids]
        except (ValueError, TypeError):
            task_ids = [active_task_id]
        for tid in task_ids:
            if tid:
                celery_app.control.revoke(tid, terminate=True)
    except Exception:
        logger.warning("Failed to revoke active tasks (task_id=%s)", active_task_id, exc_info=True)


async def _append_task_id(run_id: int, task_id: str, *, run_service: Any | None = None) -> None:
    """Atomically append a task id via the configured run storage backend."""
    if run_service is None:
        run_service = import_module("creator_service.run_service").run_service

    run_service_obj = cast(Any, run_service)
    await run_service_obj.storage.append_active_task_id(run_id, task_id)


async def cas_dispatch_with_rollback(
    *,
    run_id: int,
    expected_stages: frozenset[str],
    target_stage: str,
    dispatcher: Callable[..., str],
    dispatcher_args: Mapping[str, Any],
    run_service: Any,
    rollback_stage: str,
    rollback_restart_from: str | None,
    enqueue_error_detail: str,
    restart_from_stage: str | None = None,
) -> dict[str, object]:
    run_service_obj = cast(Any, run_service)
    updates: dict[str, object] = {"current_stage": target_stage}
    restart_stage = restart_from_stage or target_stage
    if rollback_stage == restart_stage:
        updates["restart_from"] = target_stage

    ok, row = await run_service_obj.storage.conditional_update_run(
        run_id,
        updates,
        expected_stages=expected_stages,
    )
    if not ok:
        if row is None:
            raise HTTPException(status_code=404, detail="Run not found")
        raise HTTPException(
            status_code=409,
            detail=f"Stage conflict: run is now in '{row.get('current_stage')}'",
        )

    try:
        task_id = dispatcher(**dict(dispatcher_args))
    except Exception:
        await run_service_obj.storage.conditional_update_run(
            run_id,
            {"current_stage": rollback_stage, "restart_from": rollback_restart_from},
            expected_stages=frozenset({target_stage}),
        )
        raise HTTPException(status_code=503, detail=enqueue_error_detail) from None

    await _append_task_id(run_id, task_id, run_service=run_service_obj)
    return {
        "task_id": task_id,
        "run_id": run_id,
        "current_stage": target_stage,
    }

_EXPORTED_RUN_HELPERS = (_revoke_active_tasks, _append_task_id)
