"""Shared validation and run task helpers for creator routes."""

import logging
from collections.abc import Mapping
from importlib import import_module

from fastapi import HTTPException

logger = logging.getLogger(__name__)

from creator_service.task_dispatch_service import (
    cas_dispatch_with_rollback,
    dispatch_generate_audio,
    dispatch_generate_scene_image,
    dispatch_generate_script,
    dispatch_generate_subtitles,
    dispatch_generate_visual_plan,
    dispatch_paragraph_audio,
    dispatch_paragraph_subtitles,
    dispatch_render_video,
)

__all__ = [
    "validate_model_key",
    "validate_render_profile",
    "validate_model_defaults",
    "_revoke_active_tasks_for_run",
    "_has_active_tasks_for_run",
    "cas_dispatch_with_rollback",
    "dispatch_generate_audio",
    "dispatch_generate_scene_image",
    "dispatch_generate_script",
    "dispatch_generate_subtitles",
    "dispatch_generate_visual_plan",
    "dispatch_paragraph_audio",
    "dispatch_paragraph_subtitles",
    "dispatch_render_video",
]


def validate_model_key(model_key: str) -> None:
    try:
        from creator_provider.registry import ProviderRegistry

        registry = ProviderRegistry.create_default()
        registry.resolve(model_key)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown model key '{model_key}'. "
                "Use GET /api/creator/models to list available models."
            ),
        ) from None


def validate_render_profile(profile_name: str) -> None:
    try:
        __import__("creator_service.render_profile")
    except ImportError:
        return

    known_profiles = {"shorts_default", "high_quality", "fast_preview"}
    if profile_name not in known_profiles:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown render profile '{profile_name}'. "
                f"Available profiles: {sorted(known_profiles)}."
            ),
        )


def validate_model_defaults(model_defaults: Mapping[str, str] | None) -> None:
    if not model_defaults:
        return

    validators = {
        "script_model": validate_model_key,
        "image_model": validate_model_key,
        "tts_model": validate_model_key,
        "subtitle_model": validate_model_key,
        "render_profile": validate_render_profile,
    }

    for key, value in model_defaults.items():
        validator = validators.get(key)
        if validator is None:
            raise HTTPException(
                status_code=400,
                detail=(f"Unknown model default key '{key}'. Allowed keys: {sorted(validators)}."),
            )
        validator(value)


async def _revoke_active_tasks_for_run(run_id: int) -> None:
    try:
        celery_app = __import__("celery_app").celery_app
        tracking_service = import_module(
            "creator_service.task_tracking_service"
        ).task_tracking_service
        celery_ids = await tracking_service.revoke_active_tasks(run_id)
        for tid in celery_ids:
            celery_app.control.revoke(tid, terminate=True)
    except Exception:
        logger.warning("Failed to revoke active tasks for run %d", run_id, exc_info=True)


async def _has_active_tasks_for_run(run_id: int) -> bool:
    tracking_service = import_module("creator_service.task_tracking_service").task_tracking_service
    return await tracking_service.has_active_tasks(run_id)


_EXPORTED_RUN_HELPERS = (_revoke_active_tasks_for_run, _has_active_tasks_for_run)
