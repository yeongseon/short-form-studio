from __future__ import annotations

from dataclasses import dataclass

import pytest
from creator_service.media_retention import RetentionSweepResult

from tasks import sweep_media_retention


@dataclass(frozen=True, slots=True)
class EnabledPolicy:
    enabled: bool = True
    dry_run: bool = True


@pytest.mark.asyncio
async def test_sweep_once_paginates_all_workspaces(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given storage returns a full workspace page followed by one more workspace.
    seen: list[int] = []

    class Storage:
        async def list_retention_workspaces(self, limit, *, after_workspace_id=None):
            if after_workspace_id is None:
                return list(range(1, 1001))
            if after_workspace_id == 1000:
                return [1001]
            return []

    class Service:
        def __init__(self, storage, objects, policy):
            pass

        async def sweep_workspace(self, workspace_id, *, now):
            seen.append(workspace_id)
            return RetentionSweepResult(0, 0, True, True)

    monkeypatch.setattr(sweep_media_retention, "PostgresMediaAssetStorage", Storage)
    monkeypatch.setattr(sweep_media_retention, "MediaRetentionService", Service)
    monkeypatch.setattr(sweep_media_retention, "MediaRetentionPolicy", type("Policy", (), {"from_env": EnabledPolicy}))
    monkeypatch.setattr(sweep_media_retention, "get_storage_backend", lambda: None)

    # When one scheduled sweep runs.
    await sweep_media_retention._sweep_once()

    # Then the workspace after the first 1,000 is swept exactly once.
    assert seen == list(range(1, 1002))
