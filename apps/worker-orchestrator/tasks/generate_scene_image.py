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

Idempotency:
    IDEMPOTENT - Safe to retry with caveats:
    - Stage guard rejects if run has progressed past VISUAL_ASSET_REVIEW.
    - Multiple invocations of the same task generate NEW assets (different UUIDs).
      Each asset has a version number; is_active=True marks the latest as active.
    - If a task completes an image but crashes before returning, worker redelivery
      will create a duplicate asset. The service handles this gracefully:
      only the latest version is marked active; old versions remain accessible.
    - For deterministic idempotency (no duplicate assets), caller should deduplicate
      task invocations or check active asset before invoking.
    - Idempotency guaranteed by acks_late + task_reject_on_worker_lost for task delivery.

Side effects:
    - Filesystem: Saves PNG images to data/artifacts/{run_id}/scenes/{scene_id}-{uuid}.png
    - Database: Creates VisualAsset records with path, version, model_used, provider.
    - Database: Atomically transitions run stage to VISUAL_ASSET_REVIEW on success or FAILED
      on total failure (conditional_update_run).
    - GPU Resource: Acquires/releases GPU lock in Redis per-scene (if provider requires GPU).

Retry safety:
    SAFE FOR RETRY - Partial failure handled gracefully:
    - max_retries=3
    - autoretry_for=(ProviderTimeoutError, RateLimitError)
    - retry_backoff=True, retry_jitter=True
    - soft_time_limit=600s, hard time_limit=660s (double other tasks for batch processing)
    On timeout: Task transitions run to FAILED atomically before raising.
    On partial failure: Task returns success + reports failed_scenes in result;
    caller decides whether to retry failed scenes or accept partial output.
"""

# pyright: reportMissingImports=false
# ruff: noqa: E402

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

redis: Any  # optional dependency; may be None at runtime
try:
    import redis
except ImportError:
    redis = None

from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_domain.sanitize import sanitize_path_component
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_provider.gpu_lock import acquire_gpu_lock, release_gpu_lock
from creator_provider.registry import ProviderRegistry
from creator_service.cost_config import COST_SCENE_IMAGE
from creator_service.run_service import run_service as _run_service
from creator_service.telemetry import trace_task
from creator_service.task_tracking_service import task_tracking_service as _task_tracking_service
from creator_service.usage_service import record_provider_call, resolve_workspace_id_from_run
from creator_service.visual_asset_service import visual_asset_service as _visual_asset_service
from creator_service.visual_plan_service import visual_plan_service as _visual_plan_service

logger = logging.getLogger(__name__)

_ALLOWED_STAGES = frozenset(
    {
        RunStage.VISUAL_PLAN_REVIEW,
        RunStage.VISUAL_ASSET_GENERATING,
        RunStage.VISUAL_ASSET_REVIEW,
    }
)

# Stages where successful image generation can still safely land.
# Batch generation starts from VISUAL_ASSET_GENERATING, while single-scene
# generation/regeneration may be triggered from review stages without an
# intermediate stage transition.
_SAFE_SUCCESS_STAGES = frozenset(
    {
        RunStage.VISUAL_PLAN_REVIEW.value,
        RunStage.VISUAL_ASSET_GENERATING.value,
        RunStage.VISUAL_ASSET_REVIEW.value,
    }
)

# FAILED should only be written while the run is still pre-review or actively
# generating. Once a run has advanced to asset review, a stale failing task
# must not downgrade it.
_SAFE_FAILURE_STAGES = frozenset(
    {
        RunStage.VISUAL_PLAN_REVIEW.value,
        RunStage.VISUAL_ASSET_GENERATING.value,
    }
)

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


async def _remove_active_task_id_best_effort(run_id: int, task_id: str) -> None:
    remover: Any = getattr(_run_service.storage, "remove_active_task_id", None)
    if not callable(remover):
        return
    try:
        maybe_result = remover(run_id, task_id)
        if asyncio.iscoroutine(maybe_result):
            await maybe_result
    except Exception:
        logger.exception("Failed to remove active task id %s for run %d", task_id, run_id)


@celery_app.task(
    bind=True,
    autoretry_for=(ProviderTimeoutError, RateLimitError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=600,
    time_limit=660,
    name="generate_scene_image",
)
@trace_task("generate_scene_image")
def generate_scene_image(
    self,
    run_id: int,
    scene_id: str | None = None,
    model_key: str = "sd15",
    prompt_override: str | None = None,
    is_active: bool = True,
    image_params: dict[str, Any] | None = None,
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
        image_params: Optional dict of per-request image generation params
                      (steps, sampler_name, negative_prompt, cfg_scale, etc.).
                      Merged on top of registry default_params.
    """
    start_time = datetime.now(timezone.utc)
    start_iso = start_time.isoformat()
    task_id = str(getattr(getattr(self, "request", None), "id", None) or f"run-{run_id}")
    # Idempotency: acks_late + task_reject_on_worker_lost ensures redelivery on crash.
    # If the run has already advanced past this stage, the worker's stage check will
    # naturally skip processing (handled by run_service stage validation).

    provider_type: str | None = None
    endpoint: str | None = None

    async def _run_task() -> dict[str, object]:
        nonlocal provider_type, endpoint
        try:
            try:
                await _task_tracking_service.record_task_start(
                    run_id, "generate_scene_image", task_id
                )
                await _task_tracking_service.mark_running(task_id)
            except Exception:
                logger.warning("Failed to record task start", exc_info=True)
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
            if run.get("status") == "cancelled":
                raise _StageGuardError(f"Run {run_id} is cancelled")
            workspace_id = await resolve_workspace_id_from_run(run_id)
            project_id = run.get("project_id")

            # 2. Fetch active visual plan.
            plan = await _visual_plan_service.get_active_plan(run_id)
            if plan is None:
                raise _StageGuardError(f"No active visual plan for run {run_id}")

            # 3. Determine scenes to generate.
            if scene_id is not None:
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
                    effective_prompt = (
                        prompt_override
                        if prompt_override is not None and scene_id is not None
                        else target_scene.prompt
                    )

                    if entry.requires_gpu:
                        redis_client = _get_redis_client()
                        if redis_client is None:
                            raise RuntimeError(
                                "Redis client is unavailable; cannot acquire GPU lock"
                            )
                        scene_task_id = f"{task_id}:{target_scene.scene_id}"
                        acquire_gpu_lock(redis_client, scene_task_id)
                        lock_acquired = True
                        gpu_lock_acquired_at = _utc_now_iso()

                    try:
                        params = dict(entry.default_params or {})
                        if image_params:
                            params.update(image_params)
                        safe_scene_id = sanitize_path_component(
                            target_scene.scene_id, label="scene_id"
                        )
                        target_path = str(asset_dir / f"{safe_scene_id}-{uuid4().hex}.png")
                        params["output_path"] = target_path
                        try:
                            await provider.generate(effective_prompt, params)
                        except (TimeoutError, ConnectionError) as exc:
                            raise ProviderTimeoutError(
                                "Provider timed out during scene image generation "
                                f"for run {run_id} scene {target_scene.scene_id}"
                            ) from exc
                        except SoftTimeLimitExceeded:
                            raise
                        except Exception as exc:
                            message = str(exc).lower()
                            if "429" in message or "rate" in message:
                                raise RateLimitError(
                                    "Provider rate limited scene image generation "
                                    f"for run {run_id} scene {target_scene.scene_id}"
                                ) from exc
                            raise ProviderError(
                                "Provider failed scene image generation "
                                f"for run {run_id} scene {target_scene.scene_id}"
                            ) from exc
                        try:
                            await record_provider_call(
                                run_id,
                                entry.provider_type,
                                model_key,
                                "image_gen",
                                cost_usd=COST_SCENE_IMAGE,
                                workspace_id=workspace_id,
                                project_id=project_id,
                            )
                        except Exception:
                            logger.warning("Failed to record provider usage", exc_info=True)

                        from creator_service.artifact_storage_integration import (
                            store_artifact_file,
                        )

                        try:
                            uploaded = store_artifact_file(run_id, target_path, "image/png")
                        except Exception as exc:
                            logger.error(
                                "Failed to upload artifact %s to remote storage: %s",
                                target_path,
                                exc,
                            )
                            raise

                        asset = await _visual_asset_service.create_asset(
                            run_id=run_id,
                            scene_id=target_scene.scene_id,
                            asset_path=target_path,
                            prompt_snapshot=effective_prompt,
                            model_used=model_key,
                            provider_type=entry.provider_type,
                            storage_provider=uploaded.storage_provider,
                            storage_key=uploaded.key,
                            is_active=is_active,
                        )

                        scene_result.update(
                            {
                                "status": "success",
                                "asset_id": asset.id,
                                "asset_path": asset.asset_path,
                                "version": asset.version,
                                "gpu_lock_acquired_at": gpu_lock_acquired_at,
                                "gpu_lock_released_at": None,
                            }
                        )
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

                except SoftTimeLimitExceeded:
                    raise
                except Exception as exc:
                    scene_result.update(
                        {
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
                    failed_scenes.append(scene_result)
                    logger.error(
                        "Failed to generate image for scene %s in run %d: %s",
                        target_scene.scene_id,
                        run_id,
                        exc,
                    )

            total = len(target_scenes)
            succeeded = len(results)
            failed = len(failed_scenes)

            if failed == total:
                overall_status = "failed"
                try:
                    applied, _ = await _run_service.storage.conditional_update_run(
                        run_id,
                        {
                            "current_stage": RunStage.FAILED,
                            "status": "failed",
                        },
                        expected_stages=_SAFE_FAILURE_STAGES,
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
                overall_status = "success" if failed == 0 else "partial"
                applied, _ = await _run_service.storage.conditional_update_run(
                    run_id,
                    {
                        "current_stage": RunStage.VISUAL_ASSET_REVIEW,
                        "status": "running",
                    },
                    expected_stages=_SAFE_SUCCESS_STAGES,
                )
                if not applied:
                    logger.info(
                        "Run %d stage changed during image generation -- skipping transition",
                        run_id,
                    )

            end_time = datetime.now(timezone.utc)
            duration_seconds = (end_time - start_time).total_seconds()
            try:
                await _task_tracking_service.mark_success(task_id)
            except Exception:
                logger.warning("Failed to record task success", exc_info=True)

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
        finally:
            await _remove_active_task_id_best_effort(run_id, task_id)

    try:
        return asyncio.run(_run_task())
    except _StageGuardError:
        # Validation rejection — do NOT mutate run state to FAILED.
        # A stale/duplicate task should not downgrade a run already past generation.
        try:
            asyncio.run(_task_tracking_service.mark_rejected(task_id, "stage_guard"))
        except Exception:
            logger.warning("Failed to record task rejection", exc_info=True)
        raise
    except SoftTimeLimitExceeded:
        logger.error("Task timed out for run %s", run_id)
        # Transition run to FAILED so it doesn't stay stuck in generating stage
        try:
            asyncio.run(
                _run_service.storage.conditional_update_run(
                    run_id,
                    {
                        "current_stage": RunStage.FAILED.value,
                        "status": "failed",
                    },
                    expected_stages=_SAFE_FAILURE_STAGES,
                )
            )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after timeout", run_id)
        raise
    except Exception as exc:
        if (
            isinstance(exc, (ProviderTimeoutError, RateLimitError))
            and self.request.retries < self.max_retries
        ):
            raise
        try:
            asyncio.run(
                _task_tracking_service.mark_failed(task_id, type(exc).__name__, str(exc)[:500])
            )
        except Exception:
            logger.warning("Failed to record task failure", exc_info=True)
        # Unexpected error (not scene-level) — atomic conditional fail.
        try:
            applied, _ = asyncio.run(
                _run_service.storage.conditional_update_run(
                    run_id,
                    {
                        "current_stage": RunStage.FAILED,
                        "status": "failed",
                    },
                    expected_stages=_SAFE_FAILURE_STAGES,
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
