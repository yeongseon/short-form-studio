# pyright: reportMissingImports=false
# ruff: noqa: E402

from __future__ import annotations

import json
import logging
from typing import Any


from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_domain.models.visual_plan import VisualScene
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_provider.registry import ProviderRegistry
from creator_service.cost_config import COST_VISUAL_PLAN
from creator_service.script_service import script_service as _script_service
from creator_service.telemetry import trace_task
from creator_service.usage_service import record_provider_call
from creator_service.visual_plan_service import visual_plan_service as _visual_plan_service
from tasks.task_runner import GpuLockContext, TaskContext, TaskResult, TaskRunnerConfig, run_task

logger = logging.getLogger(__name__)

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
    lines: list[str] = []
    for section in sections:
        section_id = section.get("section_id", "unknown")
        section_type = section.get("type", "unknown")
        text = section.get("text", "")
        lines.append(f"[{section_id}] ({section_type}): {text}")
    return "\n".join(lines)

def _parse_llm_response(raw: str, sections: list[dict[str, Any]]) -> list[VisualScene]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines)

    try:
        llm_scenes = json.loads(cleaned)
    except json.JSONDecodeError:
        llm_scenes = []

    if not isinstance(llm_scenes, list):
        llm_scenes = []

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
@trace_task("generate_visual_plan")
def generate_visual_plan(
    self,
    run_id: int,
    model_key: str = "qwen3-4b",
    style_preset: str | None = None,
) -> dict[str, object]:
    config = TaskRunnerConfig(
        task_name="generate_visual_plan",
        allowed_stages=frozenset({RunStage.VISUAL_PLAN_SETUP, RunStage.VISUAL_PLAN_GENERATING}),
        safe_stages=frozenset({RunStage.VISUAL_PLAN_GENERATING.value}),
        success_stage=RunStage.VISUAL_PLAN_REVIEW.value,
    )

    async def execute(ctx: TaskContext) -> TaskResult:
        draft = await _script_service.get_active_draft(run_id)
        if draft is None:
            raise ValueError(f"No script draft found for run {run_id}")

        sections: list[dict[str, Any]] = []
        if draft.structured_script:
            sections = [s.model_dump(mode="json") for s in draft.structured_script]
        elif draft.markdown_content:
            sections = [{"section_id": "sec-0", "type": "body", "text": draft.markdown_content}]
        if not sections:
            raise ValueError(f"Script draft for run {run_id} has no content")

        registry = ProviderRegistry.create_default()
        entry = registry.resolve(model_key)
        provider = registry.get_provider(model_key)

        gpu_lock = GpuLockContext(ctx.task_id)
        if entry.requires_gpu:
            gpu_lock.acquire()

        try:
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
                        f"Provider rate limited visual plan generation for run {run_id}"
                    ) from exc
                raise ProviderError(
                    f"Provider failed visual plan generation for run {run_id}"
                ) from exc
        finally:
            if entry.requires_gpu:
                gpu_lock.release()

        try:
            await record_provider_call(
                run_id,
                entry.provider_type,
                model_key,
                "llm",
                cost_usd=COST_VISUAL_PLAN,
                workspace_id=ctx.workspace_id,
                project_id=ctx.project_id,
                idempotency_key=ctx.task_id,
            )
        except Exception:
            logger.warning("Failed to record provider usage", exc_info=True)

        visual_scenes = _parse_llm_response(raw_response, sections)
        await _visual_plan_service.save_plan(
            run_id=run_id,
            scenes=visual_scenes,
            idempotency_key=ctx.task_id,
        )
        return TaskResult(
            status="success",
            extra={
                "model_key": model_key,
                "provider_type": entry.provider_type,
                "endpoint": entry.endpoint,
                "gpu_lock_acquired_at": gpu_lock.acquired_at,
                "gpu_lock_released_at": gpu_lock.released_at,
                "scene_count": len(visual_scenes),
                "error": None,
            },
        )

    return run_task(self, run_id, config, execute)
