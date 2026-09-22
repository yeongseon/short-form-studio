from httpx import ASGITransport, AsyncClient
import pytest

from .timeline_demo_support import environment
from shorts_api.app_factory import create_app


# --------------------------------------------------------------------------- #
# 1. Auth gate (P0-1): the browser path is rejected without a key.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_first_run_step1_unauthenticated_browser_is_rejected() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for path in (
            "/api/creator/workspaces/1/onboarding",
            "/api/creator/workspaces/1/demo-short/runs",
        ):
            resp = await ac.post(path) if path.endswith("runs") else await ac.get(path)
            assert resp.status_code == 401, f"{path} should gate an anonymous browser"


@pytest.mark.asyncio
async def test_first_run_step2_offline_plan_requires_no_provider(tmp_path, monkeypatch) -> None:
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        resp = await client.get("/api/creator/workspaces/1/demo-short/plan")
    assert resp.status_code == 200
    assert resp.json()["required_provider_env_vars"] == []
    assert resp.json()["estimated_total_cost_usd"] == 0
    assert await env.runs.list_runs_by_workspace(1) == []


@pytest.mark.asyncio
async def test_first_run_step3_demo_seeds_real_renderable_project(tmp_path, monkeypatch) -> None:
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        resp = await client.post("/api/creator/workspaces/1/demo-short/runs")
    assert resp.status_code == 201
    body = resp.json()
    run = await env.runs.get_run(body["run"]["id"], workspace_id=1)
    assert run is not None
    timeline = await env.timelines.load_timeline(project_id=run.project_id, workspace_id=1)
    assert timeline is not None and timeline.id == body["timeline_id"]
    asset = await env.media.get_asset(timeline.segments[0].asset_id, 1)
    assert asset is not None
    assert (tmp_path / asset.storage_key).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert body["run"]["project_id"] == body["seeded_project_id"]
    assert body["run"]["current_stage"] == "TIMELINE_REVIEW"
    assert env.dispatches == []


# --------------------------------------------------------------------------- #
# 4. Error taxonomy (P1-6): a provider auth failure is actionable, not raw.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_first_run_step4_provider_auth_failure_is_actionable_and_safe() -> None:
    from creator_provider.exceptions import ProviderAuthError
    from creator_service.actionable_errors import (
        ErrorCategory,
        build_run_failure_summary,
        failure_summary_from_code,
    )

    # A worker provider-auth failure carrying an upstream body + token.
    summary = build_run_failure_summary(
        ProviderAuthError("https://api.openai.com/v1: 401 token=sk-abcdef1234567890abcdef")
    )
    assert summary["category"] == ErrorCategory.PROVIDER_AUTH.value
    assert summary["retryable"] is False
    assert summary["recovery_steps"], "the user must get actionable recovery steps"

    blob = str(summary)
    for leak in ("sk-abcdef1234567890abcdef", "api.openai.com", "401"):
        assert leak not in blob, f"failure summary must not leak {leak!r}"

    # The read surface reconstructs the same actionable summary from the safe code.
    reconstructed = failure_summary_from_code(str(summary["code"]))
    assert reconstructed is not None
    assert reconstructed["category"] == ErrorCategory.PROVIDER_AUTH.value
    assert reconstructed["retryable"] is False
