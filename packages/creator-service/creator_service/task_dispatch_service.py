from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from collections.abc import Callable, Mapping
from importlib import import_module
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from fastapi import HTTPException

logger = logging.getLogger(__name__)

_DISPATCH_TASK_TYPES = {
    "dispatch_generate_script": "generate_script",
    "dispatch_generate_visual_plan": "generate_visual_plan",
    "dispatch_generate_audio": "generate_audio",
    "dispatch_generate_subtitles": "generate_subtitles",
    "dispatch_render_video": "render_video",
    "dispatch_generate_scene_image": "generate_scene_image",
    "dispatch_paragraph_audio": "generate_paragraph_audio",
    "dispatch_paragraph_subtitles": "generate_paragraph_subtitles",
}


class SynchronousTaskExecutionError(Exception):
    pass


class TaskDispatchService:
    def _get_trace_headers(self) -> dict[str, str]:
        telemetry = import_module("creator_service.telemetry")
        return telemetry.get_trace_headers()

    def _use_celery_dispatch(self) -> bool:
        return bool(os.environ.get("REDIS_URL"))

    def _mark_run_failed(self, run_id: int) -> None:
        async def _update_failed() -> None:
            try:
                run_service = import_module("creator_service.run_service").run_service
                await run_service.storage.update_run(
                    run_id,
                    {"current_stage": "FAILED", "status": "failed"},
                )
            except Exception:
                logger.warning("Failed to mark run %s as FAILED", run_id, exc_info=True)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_update_failed())
            return
        loop.create_task(_update_failed())

    def _dispatch_task(
        self,
        *,
        module_name: str,
        task_attr: str,
        run_id: int,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> str:
        tasks = import_module(module_name)
        task = getattr(tasks, task_attr)
        if self._use_celery_dispatch() or not hasattr(task, "run"):
            result = task.apply_async(
                args=args or [],
                kwargs=kwargs or {},
                headers=self._get_trace_headers(),
            )
            return str(result.id)

        task_id = f"sync-{task_attr}-{run_id}-{uuid4().hex[:12]}"
        sync_self = SimpleNamespace(request=SimpleNamespace(id=task_id, retries=0), max_retries=0)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(task.run, sync_self, *(args or []), **(kwargs or {}))
                future.result()
        except Exception as exc:
            logger.exception(
                "Synchronous task dispatch failed for %s (run_id=%s)", task_attr, run_id
            )
            self._mark_run_failed(run_id)
            raise SynchronousTaskExecutionError(
                f"Synchronous task execution failed for {task_attr}"
            ) from exc
        return task_id

    def dispatch_generate_script(
        self, run_id: int, idea_brief: str, model_key: str, instructions: str | None
    ) -> str:
        return self._dispatch_task(
            module_name="tasks.generate_script",
            task_attr="generate_script",
            run_id=run_id,
            args=[run_id, idea_brief, model_key, instructions],
        )

    def dispatch_generate_visual_plan(
        self, run_id: int, model_key: str, style_preset: str | None
    ) -> str:
        return self._dispatch_task(
            module_name="tasks.generate_visual_plan",
            task_attr="generate_visual_plan",
            run_id=run_id,
            args=[run_id, model_key, style_preset],
        )

    def dispatch_generate_audio(self, run_id: int, tts_model: str, voice: str) -> str:
        return self._dispatch_task(
            module_name="tasks.generate_audio",
            task_attr="generate_audio",
            run_id=run_id,
            args=[run_id],
            kwargs={"tts_model": tts_model, "voice": voice},
        )

    def dispatch_generate_subtitles(
        self, run_id: int, subtitle_model: str, subtitle_format: str
    ) -> str:
        return self._dispatch_task(
            module_name="tasks.generate_subtitles",
            task_attr="generate_subtitles",
            run_id=run_id,
            args=[run_id],
            kwargs={"subtitle_model": subtitle_model, "subtitle_format": subtitle_format},
        )

    def dispatch_render_video(self, run_id: int, render_profile: str) -> str:
        return self._dispatch_task(
            module_name="tasks.render_video",
            task_attr="render_video",
            run_id=run_id,
            args=[run_id],
            kwargs={"render_profile": render_profile},
        )

    def dispatch_generate_scene_image(
        self,
        run_id: int,
        model_key: str,
        scene_id: str | None,
        prompt_override: str | None,
        is_active: bool,
        image_params: dict[str, Any] | None = None,
    ) -> str:
        return self._dispatch_task(
            module_name="tasks.generate_scene_image",
            task_attr="generate_scene_image",
            run_id=run_id,
            args=[run_id],
            kwargs={
                "scene_id": scene_id,
                "model_key": model_key,
                "prompt_override": prompt_override,
                "is_active": is_active,
                "image_params": image_params,
            },
        )

    def dispatch_paragraph_audio(
        self, run_id: int, section_id: str, tts_model: str, voice: str
    ) -> str:
        return self._dispatch_task(
            module_name="tasks.generate_paragraph_audio",
            task_attr="generate_paragraph_audio",
            run_id=run_id,
            args=[run_id],
            kwargs={
                "section_id": section_id,
                "tts_model": tts_model,
                "voice": voice,
            },
        )

    def dispatch_paragraph_subtitles(
        self,
        run_id: int,
        section_id: str,
        subtitle_model: str,
        subtitle_format: str,
    ) -> str:
        return self._dispatch_task(
            module_name="tasks.generate_paragraph_subtitles",
            task_attr="generate_paragraph_subtitles",
            run_id=run_id,
            args=[run_id],
            kwargs={
                "section_id": section_id,
                "subtitle_model": subtitle_model,
                "subtitle_format": subtitle_format,
            },
        )

    async def cas_dispatch_with_rollback(
        self,
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
        quota_operation_type: str | None = None,
    ) -> dict[str, object]:
        run_service_obj = cast(Any, run_service)
        workspace_id_for_reservation: int | None = None
        if quota_operation_type is not None:
            from creator_service.project_service import project_service
            from creator_service.usage_service import check_workspace_quota

            run = await run_service_obj.get_run(run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="Run not found")
            project = await project_service.get_project(run.project_id)
            if project is None:
                raise HTTPException(status_code=404, detail="Project not found")
            workspace_id = cast(int | None, getattr(project, "workspace_id", None))
            if workspace_id is None:
                raise HTTPException(status_code=400, detail="Project workspace is not configured")
            workspace_id_for_reservation = workspace_id

            allowed, reason = await check_workspace_quota(
                workspace_id,
                operation_type=quota_operation_type,
            )
            if not allowed:
                raise HTTPException(status_code=429, detail=reason)

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
        except SynchronousTaskExecutionError:
            if workspace_id_for_reservation is not None and quota_operation_type is not None:
                from creator_service.usage_service import cancel_workspace_quota_reservation

                await cancel_workspace_quota_reservation(
                    workspace_id_for_reservation,
                    quota_operation_type,
                )
            raise HTTPException(status_code=500, detail="Task execution failed") from None
        except Exception:
            if workspace_id_for_reservation is not None and quota_operation_type is not None:
                from creator_service.usage_service import cancel_workspace_quota_reservation

                await cancel_workspace_quota_reservation(
                    workspace_id_for_reservation,
                    quota_operation_type,
                )
            await run_service_obj.storage.conditional_update_run(
                run_id,
                {"current_stage": rollback_stage, "restart_from": rollback_restart_from},
                expected_stages=frozenset({target_stage}),
            )
            raise HTTPException(status_code=503, detail=enqueue_error_detail) from None

        try:
            task_type = _DISPATCH_TASK_TYPES.get(getattr(dispatcher, "__name__", ""), "unknown")
            is_sync = isinstance(task_id, str) and task_id.startswith("sync-")
            if task_type != "unknown" and not is_sync:
                tracking_service = import_module(
                    "creator_service.task_tracking_service"
                ).task_tracking_service
                await tracking_service.record_task_queued(run_id, task_type, task_id)
        except Exception:
            try:
                __import__("celery_app").celery_app.control.revoke(task_id, terminate=True)
            except Exception:
                logger.warning("Failed to revoke task %s during rollback", task_id, exc_info=True)
            try:
                tracking_service = import_module(
                    "creator_service.task_tracking_service"
                ).task_tracking_service
                await tracking_service.mark_revoked(task_id)
            except Exception:
                logger.warning(
                    "Failed to mark task %s revoked during rollback", task_id, exc_info=True
                )
            if workspace_id_for_reservation is not None and quota_operation_type is not None:
                from creator_service.usage_service import cancel_workspace_quota_reservation

                await cancel_workspace_quota_reservation(
                    workspace_id_for_reservation,
                    quota_operation_type,
                )
            await run_service_obj.storage.conditional_update_run(
                run_id,
                {"current_stage": rollback_stage, "restart_from": rollback_restart_from},
                expected_stages=frozenset({target_stage}),
            )
            raise HTTPException(status_code=503, detail=enqueue_error_detail) from None
        return {
            "task_id": task_id,
            "run_id": run_id,
            "current_stage": target_stage,
        }


task_dispatch_service = TaskDispatchService()


def dispatch_generate_script(
    run_id: int, idea_brief: str, model_key: str, instructions: str | None
) -> str:
    return task_dispatch_service.dispatch_generate_script(
        run_id, idea_brief, model_key, instructions
    )


def dispatch_generate_visual_plan(run_id: int, model_key: str, style_preset: str | None) -> str:
    return task_dispatch_service.dispatch_generate_visual_plan(run_id, model_key, style_preset)


def dispatch_generate_audio(run_id: int, tts_model: str, voice: str) -> str:
    return task_dispatch_service.dispatch_generate_audio(run_id, tts_model, voice)


def dispatch_generate_subtitles(run_id: int, subtitle_model: str, subtitle_format: str) -> str:
    return task_dispatch_service.dispatch_generate_subtitles(
        run_id, subtitle_model, subtitle_format
    )


def dispatch_render_video(run_id: int, render_profile: str) -> str:
    return task_dispatch_service.dispatch_render_video(run_id, render_profile)


def dispatch_generate_scene_image(
    run_id: int,
    model_key: str,
    scene_id: str | None,
    prompt_override: str | None,
    is_active: bool,
    image_params: dict[str, Any] | None = None,
) -> str:
    return task_dispatch_service.dispatch_generate_scene_image(
        run_id,
        model_key,
        scene_id,
        prompt_override,
        is_active,
        image_params,
    )


def dispatch_paragraph_audio(run_id: int, section_id: str, tts_model: str, voice: str) -> str:
    return task_dispatch_service.dispatch_paragraph_audio(
        run_id,
        section_id,
        tts_model,
        voice,
    )


def dispatch_paragraph_subtitles(
    run_id: int,
    section_id: str,
    subtitle_model: str,
    subtitle_format: str,
) -> str:
    return task_dispatch_service.dispatch_paragraph_subtitles(
        run_id,
        section_id,
        subtitle_model,
        subtitle_format,
    )


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
    quota_operation_type: str | None = None,
) -> dict[str, object]:
    return await task_dispatch_service.cas_dispatch_with_rollback(
        run_id=run_id,
        expected_stages=expected_stages,
        target_stage=target_stage,
        dispatcher=dispatcher,
        dispatcher_args=dispatcher_args,
        run_service=run_service,
        rollback_stage=rollback_stage,
        rollback_restart_from=rollback_restart_from,
        enqueue_error_detail=enqueue_error_detail,
        restart_from_stage=restart_from_stage,
        quota_operation_type=quota_operation_type,
    )
