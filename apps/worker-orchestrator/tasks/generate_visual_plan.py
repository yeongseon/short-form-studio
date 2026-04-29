"""Celery task for visual plan generation via LLM providers.

Consumes an approved script draft and generates a visual plan — one scene
per script section with image-generation prompts, style tags, and mood.
Follows the same pattern as generate_script.

Idempotency:
    IDEMPOTENT - Safe to retry. Uses stage guards identical to generate_script:
    - Checks run is in VISUAL_PLAN_SETUP or VISUAL_PLAN_GENERATING before any side effects.
    - If run has advanced to VISUAL_PLAN_REVIEW or later, raises _StageGuardError without
      mutating run state.
    - Multiple invocations attempt generation; only first successful stage transition sticks
      (conditional_update_run uses compare-and-set).
    - Idempotency guaranteed by acks_late + task_reject_on_worker_lost.

Side effects:
    - Database: Saves visual plan with VisualScene objects (one per script section).
    - Database: Atomically transitions run stage to VISUAL_PLAN_REVIEW (via conditional_update_run).
    - GPU Resource: Acquires/releases GPU lock in Redis (if provider requires GPU).
    - No file creation: Results stored in database.

Retry safety:
    SAFE FOR RETRY - Same configuration as generate_script:
    - max_retries=3
    - autoretry_for=(ProviderTimeoutError, RateLimitError)
    - retry_backoff=True, retry_jitter=True
    - soft_time_limit=300s, hard time_limit=360s
    On timeout: Task transitions run to FAILED atomically before raising.
"""

Consumes an approved script draft and generates a visual plan — one scene
per script section with image-generation prompts, style tags, and mood.
Follows the same pattern as generate_script.
"""

# pyright: reportMissingImports=false
# ruff: noqa: E402

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

redis: Any  # optional dependency; may be None at runtime
try:
    import redis
except ImportError:
    redis = None

from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_domain.models.visual_plan import VisualScene
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_provider.gpu_lock import acquire_gpu_lock, release_gpu_lock
from creator_provider.registry import ProviderRegistry
from creator_service.run_service import run_service as _run_service
from creator_service.script_service import script_service as _script_service
from creator_service.visual_plan_service import visual_plan_service as _visual_plan_service

logger = logging.getLogger(__name__)

_ALLOWED_STAGES = frozenset({RunStage.VISUAL_PLAN_SETUP, RunStage.VISUAL_PLAN_GENERATING})

# Stages where writing VISUAL_PLAN_REVIEW or FAILED is safe — the run
# hasn't advanced past visual plan generation.
_SAFE_STAGES = frozenset({RunStage.VISUAL_PLAN_GENERATING.value})


class _StageGuardError(ValueError):
    """Raised when a run is not in an acceptable stage for visual plan generation.

    This is a validation/rejection error — the run state must NOT be mutated
    to FAILED because the run may already be in a later stage.
    """


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_system_prompt(style_preset: str | None = None) -> str:
    base = (
        "You are a visual planning assistant for short-form video production. "
        "Given a script with sections, generate one visual scene per section. "
        "For each scene, produce:\n"
        "- A detailed image-generation prompt (describe the visual, not the narration)\n"
        "- Style tags (e.g., cinematic, cartoon, minimalist)\n"
        "- Mood (e.g., tense, upbeat, mysterious)\n"
        "- Composition notes (e.g., close-up, wide shot, overhead)\n\n"
        "Return a JSON array of objects with keys: "
        "section_id, prompt, style_tags (array), mood, composition.\n"
        "Only return the JSON array, no markdown fencing or extra text."
    )
    if style_preset:
        base += f"\n\nStyle preset: {style_preset}"
    return base


def _build_sections_prompt(sections: list[dict[str, Any]]) -> str:
    """Format script sections into a prompt for the LLM."""
    lines: list[str] = []
    for section in sections:
        section_id = section.get("section_id", "unknown")
        section_type = section.get("type", "unknown")
        text = section.get("text", "")
        lines.append(f"[{section_id}] ({section_type}): {text}")
    return "\n".join(lines)


def _parse_llm_response(
    raw: str,
    sections: list[dict[str, Any]],
) -> list[VisualScene]:
    """Parse LLM response JSON into VisualScene domain objects.

    Maps each LLM output to the corresponding script section by section_id.
    Sections without a matching LLM output get a default scene.
    """
    # Try to parse JSON — strip markdown fencing if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Remove ```json ... ``` fencing
        lines = cleaned.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines)

    try:
        llm_scenes = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: generate default scenes for all sections
        llm_scenes = []

    if not isinstance(llm_scenes, list):
        llm_scenes = []

    # Build lookup by section_id
    llm_map: dict[str, dict[str, Any]] = {}
    for item in llm_scenes:
        if isinstance(item, dict) and "section_id" in item:
            llm_map[item["section_id"]] = item

    scenes: list[VisualScene] = []
    for idx, section in enumerate(sections):
        section_id = section.get("section_id", f"sec-{idx}")
        section_type = section.get("type", "body")
        text = section.get("text", "")

        llm_data = llm_map.get(section_id, {})

        scene = VisualScene(
            scene_id=f"scene-{section_id}",
            section_id=section_id,
            scene_index=idx,
            section_type=section_type,
            original_text=text,
            prompt=section.get("image_prompt")
            or llm_data.get("prompt", f"Visual representation of: {text[:200]}"),
            prompt_edited=bool(section.get("image_prompt")),
            prompt_source="user_edited" if section.get("image_prompt") else "auto_generated",
            style_tags=section.get("style_tags") or llm_data.get("style_tags", []),
            mood=section.get("mood") or llm_data.get("mood"),
            composition=section.get("composition") or llm_data.get("composition"),
            generation_status="pending",
            latest_asset_id=None,
        )
        scenes.append(scene)

    return scenes


def _get_redis_client() -> Any | None:
    if redis is None:
        return None
    return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


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
    soft_time_limit=300,
    time_limit=360,
    name="generate_visual_plan",
)
def generate_visual_plan(
    self,
    run_id: int,
    model_key: str = "qwen3-4b",
    style_preset: str | None = None,
) -> dict[str, object]:
    start_time = datetime.now(timezone.utc)
    start_iso = start_time.isoformat()
    task_id = str(getattr(getattr(self, "request", None), "id", None) or f"run-{run_id}")
    # Idempotency: acks_late + task_reject_on_worker_lost ensures redelivery on crash.
    # If the run has already advanced past this stage, the worker's stage check will
    # naturally skip processing (handled by run_service stage validation).

    provider_type: str | None = None
    endpoint: str | None = None
    gpu_lock_acquired_at: str | None = None
    gpu_lock_released_at: str | None = None
    redis_client: Any | None = None
    lock_acquired = False

    async def _run_task() -> dict[str, object]:
        nonlocal provider_type, endpoint, gpu_lock_acquired_at, gpu_lock_released_at
        nonlocal redis_client, lock_acquired
        try:
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
                    f"expected one of {', '.join(s.value for s in _ALLOWED_STAGES)}"
                )
            if run.get("status") == "cancelled":
                raise _StageGuardError(f"Run {run_id} is cancelled")

            # 2. Fetch approved script draft.
            draft = await _script_service.get_active_draft(run_id)
            if draft is None:
                raise _StageGuardError(f"No script draft found for run {run_id}")

            sections: list[dict[str, Any]] = []
            if draft.structured_script:
                sections = [s.model_dump(mode="json") for s in draft.structured_script]
            elif draft.markdown_content:
                sections = [{"section_id": "sec-0", "type": "body", "text": draft.markdown_content}]

            if not sections:
                raise _StageGuardError(f"Script draft for run {run_id} has no content")

            # 3. Provider resolution (sync — blocks briefly, fine in Celery worker).
            registry = ProviderRegistry.create_default()
            entry = registry.resolve(model_key)
            provider = registry.get_provider(model_key)

            provider_type = entry.provider_type
            endpoint = entry.endpoint

            # 4. GPU lock acquisition (sync).
            if entry.requires_gpu:
                redis_client = _get_redis_client()
                if redis_client is None:
                    raise RuntimeError("Redis client is unavailable; cannot acquire GPU lock")
                acquire_gpu_lock(redis_client, task_id)
                lock_acquired = True
                gpu_lock_acquired_at = _utc_now_iso()

            try:
                # 5. Generation: send script sections to LLM for visual planning.
                system_prompt = _build_system_prompt(style_preset)
                sections_prompt = _build_sections_prompt(sections)
                full_prompt = f"{system_prompt}\n\n---\nScript sections:\n{sections_prompt}"

                params = dict(entry.default_params or {})
                try:
                    raw_response = await provider.generate(full_prompt, params)
                except (TimeoutError, ConnectionError) as exc:
                    raise ProviderTimeoutError(
                        f"Provider timed out during visual plan generation for run {run_id}"
                    ) from exc
                except SoftTimeLimitExceeded:
                    raise
                except Exception as exc:
                    message = str(exc).lower()
                    if "429" in message or "rate" in message:
                        raise RateLimitError(
                            f"Provider rate limited visual plan generation for run {run_id}"
                        ) from exc
                    raise ProviderError(
                        f"Provider failed visual plan generation for run {run_id}"
                    ) from exc

                # 6. Parse LLM response into VisualScene objects.
                visual_scenes = _parse_llm_response(raw_response, sections)

                # 7. Save visual plan via service.
                await _visual_plan_service.save_plan(
                    run_id=run_id,
                    scenes=visual_scenes,
                )

                # 8. Atomic success transition: only advance if run is still in a
                # generating-compatible stage.
                applied, _ = await _run_service.storage.conditional_update_run(
                    run_id,
                    {
                        "current_stage": RunStage.VISUAL_PLAN_REVIEW.value,
                        "status": "running",
                    },
                    expected_stages=_SAFE_STAGES,
                )
                if not applied:
                    logger.info(
                        "Run %d stage changed during visual plan generation -- skipping transition",
                        run_id,
                    )
            finally:
                if lock_acquired:
                    try:
                        release_gpu_lock(redis_client, task_id)
                        gpu_lock_released_at = _utc_now_iso()
                    except Exception:
                        logger.exception("Failed to release GPU lock for task %s", task_id)

            end_time = datetime.now(timezone.utc)
            duration_seconds = (end_time - start_time).total_seconds()
            return {
                "task_id": task_id,
                "run_id": run_id,
                "model_key": model_key,
                "provider_type": provider_type,
                "endpoint": endpoint,
                "gpu_lock_acquired_at": gpu_lock_acquired_at,
                "gpu_lock_released_at": gpu_lock_released_at,
                "scene_count": len(visual_scenes),
                "start_time": start_iso,
                "end_time": end_time.isoformat(),
                "duration_seconds": duration_seconds,
                "status": "success",
                "error": None,
            }
        finally:
            await _remove_active_task_id_best_effort(run_id, task_id)

    try:
        return asyncio.run(_run_task())
    except _StageGuardError:
        # Validation rejection — do NOT mutate run state to FAILED.
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
                    expected_stages=_SAFE_STAGES,
                )
            )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after timeout", run_id)
        raise
    except Exception:
        # Atomic conditional fail: only mark FAILED if run is still in a
        # generating-compatible stage.
        try:
            applied, _ = asyncio.run(
                _run_service.storage.conditional_update_run(
                    run_id,
                    {
                        "current_stage": RunStage.FAILED.value,
                        "status": "failed",
                    },
                    expected_stages=_SAFE_STAGES,
                )
            )
            if not applied:
                logger.info(
                    "Run %d stage changed during visual plan generation -- skipping FAILED transition",
                    run_id,
                )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after task error", run_id)

        raise
