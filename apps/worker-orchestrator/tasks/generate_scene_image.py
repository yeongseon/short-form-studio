# pyright: reportMissingImports=false
# ruff: noqa: E402

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_domain.sanitize import sanitize_path_component
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_provider.registry import get_default_registry
from creator_service.cost_config import COST_SCENE_IMAGE
from creator_service.run_service import run_service as _run_service
from creator_service.telemetry import trace_task
from creator_service.usage_service import record_provider_call
from creator_service.visual_asset_service import visual_asset_service as _visual_asset_service
from creator_service.visual_plan_service import visual_plan_service as _visual_plan_service
from tasks.task_runner import GpuLockContext, TaskContext, TaskResult, TaskRunnerConfig, run_task

logger = logging.getLogger(__name__)
_ARTIFACTS_BASE = os.getenv("ARTIFACT_ROOT", "data/artifacts")
_SAFE_SUCCESS_STAGES = frozenset(
    {
        RunStage.VISUAL_PLAN_REVIEW.value,
        RunStage.VISUAL_ASSET_GENERATING.value,
        RunStage.VISUAL_ASSET_REVIEW.value,
    }
)
_SAFE_FAILURE_STAGES = frozenset(
    {
        RunStage.VISUAL_PLAN_REVIEW.value,
        RunStage.VISUAL_ASSET_GENERATING.value,
    }
)

def _asset_dir(run_id: int) -> Path:
    return Path(_ARTIFACTS_BASE) / str(run_id) / "scenes"

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
    config = TaskRunnerConfig(
        task_name="generate_scene_image",
        allowed_stages=frozenset(
            {
                RunStage.VISUAL_PLAN_REVIEW,
                RunStage.VISUAL_ASSET_GENERATING,
                RunStage.VISUAL_ASSET_REVIEW,
            }
        ),
        safe_stages=_SAFE_SUCCESS_STAGES,
        safe_failure_stages=_SAFE_FAILURE_STAGES,
        success_stage=None,
    )

    async def execute(ctx: TaskContext) -> TaskResult:
        plan = await _visual_plan_service.get_active_plan(run_id)
        if plan is None:
            raise ValueError(f"No active visual plan for run {run_id}")

        if scene_id is not None:
            target_scenes = [s for s in plan.scenes if s.scene_id == scene_id]
            if not target_scenes:
                raise ValueError(f"Scene '{scene_id}' not found in visual plan for run {run_id}")
        else:
            target_scenes = list(plan.scenes)
        if not target_scenes:
            raise ValueError(f"Visual plan for run {run_id} has no scenes")

        registry = get_default_registry()
        entry = registry.resolve(model_key)
        provider = registry.get_provider(model_key)
        asset_dir = _asset_dir(run_id)
        asset_dir.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, object]] = []
        failed_scenes: list[dict[str, object]] = []

        for target_scene in target_scenes:
            scene_result: dict[str, object] = {
                "scene_id": target_scene.scene_id,
                "status": "pending",
            }
            effective_prompt = (
                prompt_override
                if prompt_override is not None and scene_id is not None
                else target_scene.prompt
            )
            gpu_lock = GpuLockContext(f"{ctx.task_id}:{target_scene.scene_id}")

            try:
                if entry.requires_gpu:
                    gpu_lock.acquire()
                try:
                    params = dict(entry.default_params or {})
                    if image_params:
                        params.update(image_params)
                    safe_scene_id = sanitize_path_component(target_scene.scene_id, label="scene_id")
                    target_path = str(asset_dir / f"{safe_scene_id}-{uuid4().hex}.png")
                    params["output_path"] = target_path
                    try:
                        await provider.generate(effective_prompt, params)
                    except (TimeoutError, ConnectionError) as exc:
                        raise ProviderTimeoutError(
                            "Provider timed out during scene image generation "
                            f"for run {run_id} scene {target_scene.scene_id}"
                        ) from exc
                    except ProviderTimeoutError:
                        raise
                    except RateLimitError:
                        raise
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
                finally:
                    if entry.requires_gpu:
                        gpu_lock.release()

                try:
                    await record_provider_call(
                        run_id,
                        entry.provider_type,
                        model_key,
                        "image_gen",
                        cost_usd=COST_SCENE_IMAGE,
                        workspace_id=ctx.workspace_id,
                        project_id=ctx.project_id,
                        idempotency_key=f"{ctx.task_id}:{target_scene.scene_id}",
                    )
                except Exception:
                    logger.warning("Failed to record provider usage", exc_info=True)

                from creator_service.artifact_storage_integration import store_artifact_file

                uploaded = store_artifact_file(run_id, target_path, "image/png")
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
                    idempotency_key=f"{ctx.task_id}:{target_scene.scene_id}",
                )

                scene_result.update(
                    {
                        "status": "success",
                        "asset_id": asset.id,
                        "asset_path": asset.asset_path,
                        "version": asset.version,
                        "gpu_lock_acquired_at": gpu_lock.acquired_at,
                        "gpu_lock_released_at": gpu_lock.released_at,
                    }
                )
                results.append(scene_result)
            except SoftTimeLimitExceeded:
                raise
            except ProviderTimeoutError:
                raise
            except RateLimitError:
                raise
            except Exception as exc:
                scene_result.update({"status": "failed", "error": str(exc)})
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
            status = "failed"
            applied, _ = await _run_service.storage.conditional_update_run(
                run_id,
                {"current_stage": RunStage.FAILED, "status": "failed"},
                expected_stages=_SAFE_FAILURE_STAGES,
            )
            if not applied:
                logger.info(
                    "Run %d stage changed during image generation -- skipping FAILED transition",
                    run_id,
                )
        else:
            status = "success" if failed == 0 else "partial"
            applied, _ = await _run_service.storage.conditional_update_run(
                run_id,
                {"current_stage": RunStage.VISUAL_ASSET_REVIEW, "status": "running"},
                expected_stages=_SAFE_SUCCESS_STAGES,
            )
            if not applied:
                logger.info(
                    "Run %d stage changed during image generation -- skipping transition",
                    run_id,
                )

        return TaskResult(
            status=status,
            extra={
                "model_key": model_key,
                "provider_type": entry.provider_type,
                "endpoint": entry.endpoint,
                "scene_id": scene_id,
                "total_scenes": total,
                "succeeded": succeeded,
                "failed": failed,
                "scene_results": results + failed_scenes,
            },
        )

    return run_task(self, run_id, config, execute)
