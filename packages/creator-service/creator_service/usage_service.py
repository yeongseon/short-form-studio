from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from creator_domain.models import UsageEvent, UsageSummary, WorkspaceQuota

logger = logging.getLogger(__name__)


class UsageStorageBackend(Protocol):
    async def record_event(self, row: dict[str, Any]) -> dict[str, Any]: ...

    async def list_by_workspace(
        self, workspace_id: int, since: datetime
    ) -> list[dict[str, Any]]: ...

    async def list_by_run(self, run_id: int) -> list[dict[str, Any]]: ...

    async def get_workspace_quota(self, workspace_id: int) -> dict[str, Any] | None: ...

    async def set_workspace_quota(
        self, workspace_id: int, quota: dict[str, Any]
    ) -> dict[str, Any]: ...


class InMemoryUsageStorage:
    def __init__(self) -> None:
        self._events: dict[int, dict[str, Any]] = {}
        self._quotas: dict[int, dict[str, Any]] = {}
        self._next_event_id = 1
        self._next_quota_id = 1

    async def record_event(self, row: dict[str, Any]) -> dict[str, Any]:
        saved = {
            "id": self._next_event_id,
            "created_at": datetime.now(timezone.utc),
            **row,
        }
        self._events[self._next_event_id] = saved
        self._next_event_id += 1
        return dict(saved)

    async def list_by_workspace(self, workspace_id: int, since: datetime) -> list[dict[str, Any]]:
        rows = [
            dict(row)
            for row in self._events.values()
            if row.get("workspace_id") == workspace_id and row["created_at"] >= since
        ]
        rows.sort(key=lambda row: (row["created_at"], row["id"]))
        return rows

    async def list_by_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self._events.values() if row.get("run_id") == run_id]
        rows.sort(key=lambda row: (row["created_at"], row["id"]))
        return rows

    async def get_workspace_quota(self, workspace_id: int) -> dict[str, Any] | None:
        quota = self._quotas.get(workspace_id)
        return dict(quota) if quota is not None else None

    async def set_workspace_quota(self, workspace_id: int, quota: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        current = self._quotas.get(workspace_id)
        saved = {
            "id": current["id"] if current else self._next_quota_id,
            "workspace_id": workspace_id,
            "monthly_llm_calls": int(quota["monthly_llm_calls"]),
            "monthly_image_generations": int(quota["monthly_image_generations"]),
            "monthly_tts_seconds": int(quota["monthly_tts_seconds"]),
            "monthly_cost_usd": float(quota["monthly_cost_usd"]),
            "created_at": current["created_at"] if current else now,
            "updated_at": now,
        }
        if current is None:
            self._next_quota_id += 1
        self._quotas[workspace_id] = saved
        return dict(saved)


class UsageService:
    def __init__(self, storage: UsageStorageBackend):
        self.storage = storage

    async def record_usage(
        self,
        workspace_id: int | None,
        run_id: int | None,
        provider: str,
        model_key: str,
        operation_type: str,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        image_count: int | None = None,
        audio_seconds: float | None = None,
        estimated_cost_usd: float | None = None,
        project_id: int | None = None,
    ) -> UsageEvent:
        row = await self.storage.record_event(
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "run_id": run_id,
                "provider": provider,
                "model_key": model_key,
                "operation_type": operation_type,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "image_count": image_count,
                "audio_seconds": audio_seconds,
                "estimated_cost_usd": estimated_cost_usd,
            }
        )
        return UsageEvent.from_row(row)

    async def get_monthly_summary(self, workspace_id: int) -> UsageSummary:
        now = datetime.now(timezone.utc)
        period_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        rows = await self.storage.list_by_workspace(workspace_id, since=period_start)

        total_llm_calls = 0
        total_image_generations = 0
        total_tts_seconds = 0.0
        total_estimated_cost_usd = 0.0
        by_provider: dict[str, float] = {}
        by_operation: dict[str, int] = {}

        for row in rows:
            operation_type = str(row.get("operation_type") or "")
            provider = str(row.get("provider") or "unknown")
            estimated_cost_usd = float(row.get("estimated_cost_usd") or 0.0)
            image_count = int(row.get("image_count") or 0)
            audio_seconds = float(row.get("audio_seconds") or 0.0)

            if operation_type == "llm":
                total_llm_calls += 1
            if operation_type == "image_gen":
                total_image_generations += image_count if image_count > 0 else 1
            if operation_type == "tts":
                total_tts_seconds += audio_seconds

            total_estimated_cost_usd += estimated_cost_usd
            by_provider[provider] = by_provider.get(provider, 0.0) + estimated_cost_usd
            by_operation[operation_type] = by_operation.get(operation_type, 0) + 1

        return UsageSummary(
            total_llm_calls=total_llm_calls,
            total_image_generations=total_image_generations,
            total_tts_seconds=total_tts_seconds,
            total_estimated_cost_usd=total_estimated_cost_usd,
            by_provider=by_provider,
            by_operation=by_operation,
            period_start=period_start,
            period_end=now,
        )

    async def list_run_events(self, run_id: int) -> list[UsageEvent]:
        rows = await self.storage.list_by_run(run_id)
        return [UsageEvent.from_row(row) for row in rows]

    async def check_quota(self, workspace_id: int, operation_type: str) -> tuple[bool, str]:
        summary = await self.get_monthly_summary(workspace_id)
        quota = await self.get_quota(workspace_id)

        if summary.total_estimated_cost_usd >= quota.monthly_cost_usd:
            return False, "Monthly cost quota exceeded"
        if operation_type == "llm" and summary.total_llm_calls >= quota.monthly_llm_calls:
            return False, "Monthly LLM call quota exceeded"
        if (
            operation_type == "image_gen"
            and summary.total_image_generations >= quota.monthly_image_generations
        ):
            return False, "Monthly image generation quota exceeded"
        if operation_type == "tts" and summary.total_tts_seconds >= quota.monthly_tts_seconds:
            return False, "Monthly TTS seconds quota exceeded"
        return True, "ok"

    async def get_quota(self, workspace_id: int) -> WorkspaceQuota:
        row = await self.storage.get_workspace_quota(workspace_id)
        if row is None:
            row = await self.storage.set_workspace_quota(
                workspace_id,
                {
                    "monthly_llm_calls": 1000,
                    "monthly_image_generations": 200,
                    "monthly_tts_seconds": 3600,
                    "monthly_cost_usd": 50.0,
                },
            )
        return WorkspaceQuota.from_row(row)

    async def set_quota(self, workspace_id: int, **kwargs: Any) -> WorkspaceQuota:
        current = await self.get_quota(workspace_id)
        payload = {
            "monthly_llm_calls": kwargs.get("monthly_llm_calls", current.monthly_llm_calls),
            "monthly_image_generations": kwargs.get(
                "monthly_image_generations", current.monthly_image_generations
            ),
            "monthly_tts_seconds": kwargs.get("monthly_tts_seconds", current.monthly_tts_seconds),
            "monthly_cost_usd": kwargs.get("monthly_cost_usd", current.monthly_cost_usd),
        }
        row = await self.storage.set_workspace_quota(workspace_id, payload)
        return WorkspaceQuota.from_row(row)


def _create_storage() -> UsageStorageBackend:
    import os

    if os.getenv("DATABASE_URL"):
        from .postgres_usage_storage import PostgresUsageStorage

        return PostgresUsageStorage()
    return InMemoryUsageStorage()


usage_service = UsageService(_create_storage())


async def record_provider_call(
    run_id: int,
    provider_name: str,
    model: str,
    operation_type: str = "llm",
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    image_count: int | None = None,
    audio_seconds: float | None = None,
    cost_usd: float | None = None,
    workspace_id: int | None = None,
    project_id: int | None = None,
) -> UsageEvent:
    """Record a provider call from a worker task.

    Call this after each successful provider invocation::

        from creator_service.usage_service import record_provider_call

        # After LLM call:
        await record_provider_call(
            run_id, "openai", "gpt-4o-mini", "llm",
            input_tokens=500, output_tokens=200, cost_usd=0.001,
        )

        # After image generation:
        await record_provider_call(
            run_id, "stability", "sd3-medium", "image_gen",
            image_count=1, cost_usd=0.04,
        )

        # After TTS:
        await record_provider_call(
            run_id, "elevenlabs", "multilingual-v2", "tts",
            audio_seconds=30.5, cost_usd=0.05,
        )
    """
    if workspace_id is None:
        logger.warning("Recording cost without workspace_id for run %s — possible data gap", run_id)

    return await usage_service.record_usage(
        workspace_id=workspace_id,
        run_id=run_id,
        provider=provider_name,
        model_key=model,
        operation_type=operation_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        image_count=image_count,
        audio_seconds=audio_seconds,
        estimated_cost_usd=cost_usd,
        project_id=project_id,
    )


async def resolve_workspace_id_from_run(run_id: int) -> int | None:
    """Resolve workspace_id through run -> project linkage."""
    from .project_service import project_service
    from .run_service import run_service

    run = await run_service.storage.get_run(run_id)
    if run is None:
        return None

    project_id = run.get("project_id")
    if project_id is None:
        return None

    project = await project_service.db.fetch_project(int(project_id))
    if project is None:
        return None

    workspace_id = project.get("workspace_id")
    if workspace_id is None:
        return None

    return int(workspace_id)


async def check_workspace_quota(workspace_id: int, operation_type: str = "llm") -> tuple[bool, str]:
    """Check if a workspace can perform the given operation type.

    Call at task start to verify the workspace hasn't exceeded quota::

        from creator_service.usage_service import check_workspace_quota

        allowed, reason = await check_workspace_quota(workspace_id, "llm")
        if not allowed:
            raise QuotaExceededError(reason)

    Supported operation_type values: 'llm', 'image_gen', 'tts'.
    """
    return await usage_service.check_quota(workspace_id, operation_type=operation_type)
