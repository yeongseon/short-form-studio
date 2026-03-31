"""Celery task for scene image generation via image providers.

Consumes an approved visual plan and generates images for one or all scenes.
Each generated image is stored as a VisualAsset via the visual_asset_service.

Key design decisions:
- Partial failure: if one scene fails, already-completed scenes are retained.
- Regenerated assets are created as new versions; is_active defaults to True
  (auto-replaces the previous active asset for the scene).
- GPU lock is held per-scene, not for the entire batch, so other tasks can
  interleave between scenes.
- Images are saved to local filesystem: data/artifacts/{run_id}/scenes/
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import redis
except ImportError:
    redis = None  # type: ignore[assignment]

from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_provider.gpu_lock import acquire_gpu_lock, release_gpu_lock
from creator_provider.registry import ProviderRegistry
from creator_service.run_service import run_service as _run_service
from creator_service.visual_asset_service import visual_asset_service as _visual_asset_service
from creator_service.visual_plan_service import visual_plan_service as _visual_plan_service

logger = logging.getLogger(__name__)

_ALLOWED_STAGES = frozenset({RunStage.VISUAL_PLAN_REVIEW, RunStage.VISUAL_ASSET_GENERATING})

# Stages where writing VISUAL_ASSET_REVIEW or FAILED is safe — the run
# hasn't advanced past image generation.
_SAFE_STAGES = frozenset({RunStage.VISUAL_PLAN_REVIEW, RunStage.VISUAL_ASSET_GENERATING})

# Base directory for artifact storage (relative to project root).
_ARTIFACTS_BASE = os.getenv("ARTIFACT_ROOT", "data/artifacts")


class _StageGuardError(ValueError):
    """Raised when a run is not in an acceptable stage for image generation.

    This is a validation/rejection error — the run state must NOT be mutated
    to FAILED because the run may already be in a later stage.
    """


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_redis_client() -> Any | None:
    if redis is None:
        return None
    return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


def _asset_dir(run_id: int) -> Path:
    """Return the directory for storing scene image assets."""
    return Path(_ARTIFACTS_BASE) / str(run_id) / "scenes"


@celery_app.task(bind=True, name="generate_scene_image")
def generate_scene_image(
    self,
    run_id: int,
    scene_id: str | None = None,
    model_key: str = "sd15",
    prompt_override: str | None = None,
    is_active: bool = True,
) -> dict[str, object]:
    """Generate image(s) for visual plan scenes.

    Args:
        run_id: The run to generate images for.
        scene_id: If provided, generate for this single scene only.
                  If None, generate for ALL scenes in the visual plan.
        model_key: Image model to use (default: sd15).
        prompt_override: If provided, overrides the scene prompt for a
                         single-scene generation. Ignored for all-scene mode.
        is_active: Whether new assets are marked active (default: True).
    """
    start_time = datetime.now(timezone.utc)
    start_iso = start_time.isoformat()
    task_id = str(getattr(getattr(self, "request", None), "id", None) or f"run-{run_id}")

    provider_type: str | None = None
    endpoint: str | None = None

    async def _run_task() -> dict[str, object]:
        nonlocal provider_type, endpoint

        # 1. Stage guard — reject before any side effects.
        run = await _run_service.storage.get_run(run_id)
        if run is None:
            raise _StageGuardError(f"Run {run_id} not found")

        try:
            current = RunStage(run["current_stage"])
        except ValueError as exc:
            raise _StageGuardError(
                f"Run {run_id} has invalid stage {run['current_stage']!r}"
            ) from exc
        if current not in _ALLOWED_STAGES:
            raise _StageGuardError(
                f"Run {run_id} is in stage {current.value}, "
                f"expected one of {', '.join(s for s in _ALLOWED_STAGES)}"
            )

        # 2. Fetch active visual plan.
        plan = await _visual_plan_service.get_active_plan(run_id)
        if plan is None:
            raise _StageGuardError(f"No active visual plan for run {run_id}")

        # 3. Determine scenes to generate.
        if scene_id is not None:
            # Single-scene mode.
            target_scenes = [s for s in plan.scenes if s.scene_id == scene_id]
            if not target_scenes:
                raise _StageGuardError(
                    f"Scene '{scene_id}' not found in visual plan for run {run_id}"
                )
        else:
            target_scenes = list(plan.scenes)

        if not target_scenes:
            raise _StageGuardError(f"Visual plan for run {run_id} has no scenes")

        # 4. Provider resolution (sync — blocks briefly, fine in Celery worker).
        registry = ProviderRegistry.create_default()
        entry = registry.resolve(model_key)
        provider = registry.get_provider(model_key)

        provider_type = entry.provider_type
        endpoint = entry.endpoint

        # 5. Ensure artifact output directory exists.
        asset_dir = _asset_dir(run_id)
        asset_dir.mkdir(parents=True, exist_ok=True)

        # 6. Generate images per scene.
        results: list[dict[str, object]] = []
        failed_scenes: list[dict[str, object]] = []
        redis_client: Any | None = None

        for target_scene in target_scenes:
            scene_result: dict[str, object] = {
                "scene_id": target_scene.scene_id,
                "status": "pending",
            }
            lock_acquired = False
            gpu_lock_acquired_at: str | None = None
            gpu_lock_released_at: str | None = None

            try:
                # Use prompt override for single-scene, otherwise scene prompt.
                effective_prompt = (
                    prompt_override
                    if prompt_override is not None and scene_id is not None
                    else target_scene.prompt
                )

                # GPU lock (per-scene).
                if entry.requires_gpu:
                    redis_client = _get_redis_client()
                    if redis_client is None:
                        raise RuntimeError("Redis client is unavailable; cannot acquire GPU lock")
                    scene_task_id = f"{task_id}:{target_scene.scene_id}"
                    acquire_gpu_lock(redis_client, scene_task_id)
                    lock_acquired = True
                    gpu_lock_acquired_at = _utc_now_iso()

                try:
                    # Generate image via provider.
                    params = dict(entry.default_params or {})
                    image_result = await provider.generate(effective_prompt, params)

                    # Determine asset path — provider returns image_path,
                    # or we construct one.
                    if hasattr(image_result, "image_path") and image_result.image_path:
                        asset_path = image_result.image_path
                    else:
                        # Fallback: store in our artifacts directory.
                        asset_path = str(asset_dir / f"{target_scene.scene_id}.png")

                    # Save as visual asset via service.
                    asset = await _visual_asset_service.create_asset(
                        run_id=run_id,
                        scene_id=target_scene.scene_id,
                        asset_path=asset_path,
                        prompt_snapshot=effective_prompt,
                        model_used=model_key,
                        provider_type=entry.provider_type,
                        is_active=is_active,
                    )

                    scene_result.update({
                        "status": "success",
                        "asset_id": asset.id,
                        "asset_path": asset.asset_path,
                        "version": asset.version,
                        "gpu_lock_acquired_at": gpu_lock_acquired_at,
                        "gpu_lock_released_at": None,  # Set below
                    })
                finally:
                    if lock_acquired:
                        try:
                            scene_task_id = f"{task_id}:{target_scene.scene_id}"
                            release_gpu_lock(redis_client, scene_task_id)
                            gpu_lock_released_at = _utc_now_iso()
                            scene_result["gpu_lock_released_at"] = gpu_lock_released_at
                        except Exception:
                            logger.exception(
                                "Failed to release GPU lock for scene %s",
                                target_scene.scene_id,
                            )

                results.append(scene_result)

            except Exception as exc:
                scene_result.update({
                    "status": "failed",
                    "error": str(exc),
                })
                failed_scenes.append(scene_result)
                logger.error(
                    "Failed to generate image for scene %s in run %d: %s",
                    target_scene.scene_id,
                    run_id,
                    exc,
                )
                # Continue to next scene — partial failure tolerance.

        # 7. Determine overall status and stage transition.
        total = len(target_scenes)
        succeeded = len(results)
        failed = len(failed_scenes)

        if failed == total:
            # All scenes failed — mark run as FAILED.
            overall_status = "failed"
            try:
                applied, _ = await _run_service.storage.conditional_update_run(
                    run_id,
                    {
                        "current_stage": RunStage.FAILED,
                        "status": "failed",
                    },
                    expected_stages=_SAFE_STAGES,
                )
                if not applied:
                    logger.info(
                        "Run %d stage changed during image generation -- skipping FAILED transition",
                        run_id,
                    )
            except Exception:
                logger.exception("Failed to mark run %d as FAILED", run_id)
                raise
        else:
            # At least some scenes succeeded — advance to VISUAL_ASSET_REVIEW.
            overall_status = "success" if failed == 0 else "partial"
            applied, _ = await _run_service.storage.conditional_update_run(
                run_id,
                {
                    "current_stage": RunStage.VISUAL_ASSET_REVIEW,
                    "status": "running",
                },
                expected_stages=_SAFE_STAGES,
            )
            if not applied:
                logger.info(
                    "Run %d stage changed during image generation -- skipping transition",
                    run_id,
                )

        end_time = datetime.now(timezone.utc)
        duration_seconds = (end_time - start_time).total_seconds()

        return {
            "task_id": task_id,
            "run_id": run_id,
            "model_key": model_key,
            "provider_type": provider_type,
            "endpoint": endpoint,
            "scene_id": scene_id,
            "total_scenes": total,
            "succeeded": succeeded,
            "failed": failed,
            "scene_results": results + failed_scenes,
            "start_time": start_iso,
            "end_time": end_time.isoformat(),
            "duration_seconds": duration_seconds,
            "status": overall_status,
        }

    try:
        return asyncio.run(_run_task())
    except _StageGuardError:
        # Validation rejection — do NOT mutate run state to FAILED.
        raise
    except Exception:
        # Unexpected error (not scene-level) — atomic conditional fail.
        try:
            applied, _ = asyncio.run(
                _run_service.storage.conditional_update_run(
                    run_id,
                    {
                        "current_stage": RunStage.FAILED,
                        "status": "failed",
                    },
                    expected_stages=_SAFE_STAGES,
                )
            )
            if not applied:
                logger.info(
                    "Run %d stage changed during image generation -- skipping FAILED transition",
                    run_id,
                )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after task error", run_id)

        raise
