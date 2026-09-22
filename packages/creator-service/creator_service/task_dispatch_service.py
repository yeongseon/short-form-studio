from collections.abc import Callable, Mapping

from creator_domain.task_dispatch import SynchronousTaskExecutionError as SynchronousTaskExecutionError
from pydantic import JsonValue

from creator_service.dispatch_calls import DispatchCalls
from creator_service.dispatch_cas import DispatchCAS
from creator_service.dispatch_runtime import DispatchRunService


class TaskDispatchService(DispatchCalls, DispatchCAS):
    pass


task_dispatch_service = TaskDispatchService()


def dispatch_generate_script(
    run_id: int, idea_brief: str, model_key: str, instructions: str | None,
    niche: str | None = None, language: str = "ko", task_id: str | None = None,
) -> str:
    return task_dispatch_service.dispatch_generate_script(
        run_id, idea_brief, model_key, instructions, niche=niche, language=language, task_id=task_id,
    )


def dispatch_generate_visual_plan(
    run_id: int, model_key: str, style_preset: str | None,
    niche: str | None = None, task_id: str | None = None,
) -> str:
    return task_dispatch_service.dispatch_generate_visual_plan(
        run_id, model_key, style_preset, niche=niche, task_id=task_id,
    )


def dispatch_generate_audio(run_id: int, tts_model: str, voice: str, task_id: str | None = None) -> str:
    return task_dispatch_service.dispatch_generate_audio(run_id, tts_model, voice, task_id=task_id)


def dispatch_generate_subtitles(
    run_id: int, subtitle_model: str, subtitle_format: str, task_id: str | None = None,
) -> str:
    return task_dispatch_service.dispatch_generate_subtitles(run_id, subtitle_model, subtitle_format, task_id=task_id)


def dispatch_render_video(run_id: int, render_profile: str, task_id: str | None = None) -> str:
    return task_dispatch_service.dispatch_render_video(run_id, render_profile, task_id=task_id)


def dispatch_generate_scene_image(
    run_id: int, model_key: str, scene_id: str | None, prompt_override: str | None,
    is_active: bool, image_params: dict[str, JsonValue] | None = None, task_id: str | None = None,
) -> str:
    return task_dispatch_service.dispatch_generate_scene_image(
        run_id, model_key, scene_id, prompt_override, is_active, image_params, task_id=task_id,
    )


def dispatch_paragraph_audio(
    run_id: int, section_id: str, tts_model: str, voice: str, task_id: str | None = None,
) -> str:
    return task_dispatch_service.dispatch_paragraph_audio(run_id, section_id, tts_model, voice, task_id=task_id)


def dispatch_paragraph_subtitles(
    run_id: int, section_id: str, subtitle_model: str, subtitle_format: str, task_id: str | None = None,
) -> str:
    return task_dispatch_service.dispatch_paragraph_subtitles(
        run_id, section_id, subtitle_model, subtitle_format, task_id=task_id,
    )


async def cas_dispatch_with_rollback(
    *, run_id: int, expected_stages: frozenset[str], target_stage: str,
    dispatcher: Callable[..., str], dispatcher_args: Mapping[str, JsonValue],
    run_service: DispatchRunService, rollback_stage: str, rollback_restart_from: str | None,
    enqueue_error_detail: str, restart_from_stage: str | None = None,
    quota_operation_type: str | None = None, workspace_id: int | None = None,
) -> dict[str, JsonValue]:
    return await task_dispatch_service.cas_dispatch_with_rollback(
        run_id=run_id, expected_stages=expected_stages, target_stage=target_stage,
        dispatcher=dispatcher, dispatcher_args=dispatcher_args, run_service=run_service,
        rollback_stage=rollback_stage, rollback_restart_from=rollback_restart_from,
        enqueue_error_detail=enqueue_error_detail, restart_from_stage=restart_from_stage,
        quota_operation_type=quota_operation_type, workspace_id=workspace_id,
    )
