from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from importlib import import_module
from typing import Any, cast

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


class TaskDispatchService:
    def _get_trace_headers(self) -> dict[str, str]:
        telemetry = import_module("creator_service.telemetry")
        return telemetry.get_trace_headers()

    def dispatch_generate_script(
        self, run_id: int, idea_brief: str, model_key: str, instructions: str | None
    ) -> str:
        tasks = import_module("tasks.generate_script")
        result = tasks.generate_script.apply_async(
            args=[run_id, idea_brief, model_key, instructions],
            headers=self._get_trace_headers(),
        )
        return str(result.id)

    def dispatch_generate_visual_plan(
        self, run_id: int, model_key: str, style_preset: str | None
    ) -> str:
        tasks = import_module("tasks.generate_visual_plan")
        result = tasks.generate_visual_plan.apply_async(
            args=[run_id, model_key, style_preset],
            headers=self._get_trace_headers(),
        )
        return str(result.id)

    def dispatch_generate_audio(self, run_id: int, tts_model: str, voice: str) -> str:
        tasks = import_module("tasks.generate_audio")
        result = tasks.generate_audio.apply_async(
            args=[run_id],
            kwargs={"tts_model": tts_model, "voice": voice},
            headers=self._get_trace_headers(),
        )
        return str(result.id)

    def dispatch_generate_subtitles(
        self, run_id: int, subtitle_model: str, subtitle_format: str
    ) -> str:
        tasks = import_module("tasks.generate_subtitles")
        result = tasks.generate_subtitles.apply_async(
            args=[run_id],
            kwargs={"subtitle_model": subtitle_model, "subtitle_format": subtitle_format},
            headers=self._get_trace_headers(),
        )
        return str(result.id)

    def dispatch_render_video(self, run_id: int, render_profile: str) -> str:
        tasks = import_module("tasks.render_video")
        result = tasks.render_video.apply_async(
            args=[run_id],
            kwargs={"render_profile": render_profile},
            headers=self._get_trace_headers(),
        )
        return str(result.id)

    def dispatch_generate_scene_image(
        self,
        run_id: int,
        model_key: str,
        scene_id: str | None,
        prompt_override: str | None,
        is_active: bool,
        image_params: dict[str, Any] | None = None,
    ) -> str:
        tasks = import_module("tasks.generate_scene_image")
        result = tasks.generate_scene_image.apply_async(
            args=[run_id],
            kwargs={
                "scene_id": scene_id,
                "model_key": model_key,
                "prompt_override": prompt_override,
                "is_active": is_active,
                "image_params": image_params,
            },
            headers=self._get_trace_headers(),
        )
        return str(result.id)

    def dispatch_paragraph_audio(
        self, run_id: int, section_id: str, section_text: str, tts_model: str, voice: str
    ) -> str:
        tasks = import_module("tasks.generate_paragraph_audio")
        result = tasks.generate_paragraph_audio.apply_async(
            args=[run_id],
            kwargs={
                "section_id": section_id,
                "section_text": section_text,
                "tts_model": tts_model,
                "voice": voice,
            },
            headers=self._get_trace_headers(),
        )
        return str(result.id)

    def dispatch_paragraph_subtitles(
        self,
        run_id: int,
        section_id: str,
        audio_path: str,
        subtitle_model: str,
        subtitle_format: str,
    ) -> str:
        tasks = import_module("tasks.generate_paragraph_subtitles")
        result = tasks.generate_paragraph_subtitles.apply_async(
            args=[run_id],
            kwargs={
                "section_id": section_id,
                "audio_path": audio_path,
                "subtitle_model": subtitle_model,
                "subtitle_format": subtitle_format,
            },
            headers=self._get_trace_headers(),
        )
        return str(result.id)

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
            if task_type != "unknown":
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


def dispatch_paragraph_audio(
    run_id: int, section_id: str, section_text: str, tts_model: str, voice: str
) -> str:
    return task_dispatch_service.dispatch_paragraph_audio(
        run_id,
        section_id,
        section_text,
        tts_model,
        voice,
    )


def dispatch_paragraph_subtitles(
    run_id: int,
    section_id: str,
    audio_path: str,
    subtitle_model: str,
    subtitle_format: str,
) -> str:
    return task_dispatch_service.dispatch_paragraph_subtitles(
        run_id,
        section_id,
        audio_path,
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
