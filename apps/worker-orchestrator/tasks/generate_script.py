# pyright: reportMissingImports=false
# ruff: noqa: E402

from __future__ import annotations

import logging

from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_provider.registry import get_default_registry
from creator_service.cost_config import COST_SCRIPT_GENERATION
from creator_service.script_service import script_service as _script_service
from creator_service.telemetry import trace_task
from creator_service.usage_service import record_provider_call
from tasks.task_runner import GpuLockContext, TaskContext, TaskResult, TaskRunnerConfig, run_task

logger = logging.getLogger(__name__)

def _build_prompt(idea_brief: str, instructions: str | None) -> str:
    idea = idea_brief.strip()
    if not instructions:
        return idea

    extra = instructions.strip()
    if not extra:
        return idea

    return f"{idea}\n\nAdditional instructions:\n{extra}"

@celery_app.task(
    bind=True,
    autoretry_for=(ProviderTimeoutError, RateLimitError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=300,
    time_limit=360,
    name="generate_script",
)
@trace_task("generate_script")
def generate_script(
    self,
    run_id: int,
    idea_brief: str,
    model_key: str = "qwen3-4b",
    instructions: str | None = None,
) -> dict[str, object]:
    prompt = _build_prompt(idea_brief, instructions)
    config = TaskRunnerConfig(
        task_name="generate_script",
        allowed_stages=frozenset({RunStage.IDEA_READY, RunStage.SCRIPT_GENERATING}),
        safe_stages=frozenset({RunStage.IDEA_READY.value, RunStage.SCRIPT_GENERATING.value}),
        success_stage=RunStage.SCRIPT_REVIEW.value,
    )

    async def execute(ctx: TaskContext) -> TaskResult:
        registry = get_default_registry()
        entry = registry.resolve(model_key)
        provider = registry.get_provider(model_key)

        gpu_lock = GpuLockContext(ctx.task_id)
        if entry.requires_gpu:
            gpu_lock.acquire()

        try:
            params = dict(entry.default_params or {})
            try:
                generated = await provider.generate(prompt, params)
            except (TimeoutError, ConnectionError) as exc:
                raise ProviderTimeoutError(
                    f"Provider timed out during script generation for run {run_id}"
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
                        f"Provider rate limited script generation for run {run_id}"
                    ) from exc
                raise ProviderError(f"Provider failed script generation for run {run_id}") from exc
        finally:
            if entry.requires_gpu:
                gpu_lock.release()

        try:
            await record_provider_call(
                run_id,
                entry.provider_type,
                model_key,
                "llm",
                cost_usd=COST_SCRIPT_GENERATION,
                workspace_id=ctx.workspace_id,
                project_id=ctx.project_id,
                idempotency_key=ctx.task_id,
            )
        except Exception:
            logger.warning("Failed to record provider usage", exc_info=True)

        await _script_service.save_draft(
            run_id=run_id,
            source_type="generated_by_model",
            markdown_content=generated,
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
                "prompt_summary": idea_brief[:200],
                "error": None,
            },
        )

    return run_task(self, run_id, config, execute)
