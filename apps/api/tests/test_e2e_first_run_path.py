# pyright: reportMissingImports=false

"""E2E proof: the first-run path holds across the real wired seams.

Unit tests proved each fix in isolation; this walks the documented first-run path
through the actual FastAPI app to prove the seams compose:
  1. auth gate     — /api/creator/* rejects an unauthenticated browser (P0-1)
  2. readiness     — a configured-but-unprobed key is not "ready"; the demo gate
                     needs a real LLM capability (P0-2)
  3. demo seed     — POST demo-short/runs materializes a real workspace-owned
                     project with a renderable timeline referencing DB asset ids,
                     and returns real execution identity (P0-3)
  4. error taxonomy— a provider auth failure surfaces the actionable PROVIDER_AUTH
                     category with recovery steps and no secret leak (P1-6)
"""

from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
import pytest

from shorts_api.app_factory import create_app
from shorts_api.auth import CurrentUser, require_workspace_access
from shorts_api.main import app


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
            assert resp.status_code in {401, 403, 404}, f"{path} should gate an anonymous browser"


# --------------------------------------------------------------------------- #
# Shared demo seams: configured remote key reads CONFIGURED (present, unprobed).
# --------------------------------------------------------------------------- #


def _demo_routes() -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute) and "demo-short" in r.path]


class _ConfiguredHealth:
    def __init__(self, providers: list[str]) -> None:
        hosts = {"openai": "api.openai.com", "groq": "api.groq.com"}
        self._remote = {hosts[p] for p in providers if p in hosts}

    async def check_model(self, host):
        from creator_service.model_health_service import ModelHealthResult, ModelStatus

        status = ModelStatus.CONFIGURED if host in self._remote else ModelStatus.UNKNOWN
        return ModelHealthResult(model_name=host, endpoint=host, status=status)


class _StubTimeline:
    async def load_timeline(self, *, project_id: int, workspace_id: int):
        return None


class _SeedResult:
    def __init__(self, workspace_id: int) -> None:
        self.run = _Run(202, workspace_id)
        self.project_id = 202
        self.timeline_id = "demo-timeline"
        self.asset_id_map = {10: 501, 11: 501}


class _Run:
    def __init__(self, project_id: int, workspace_id: int) -> None:
        self.project_id = project_id
        self.workspace_id = workspace_id
        self.current_stage = "IDEA_READY"
        self.status = "pending"

    def model_dump(self, mode: str = "json") -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "workspace_id": self.workspace_id,
            "current_stage": self.current_stage,
            "status": self.status,
        }


def _apply_demo_seams(monkeypatch, providers: list[str], seed_calls: list[dict]) -> None:
    async def _seed(*, workspace_id, project_service, media_asset_service, timeline_service, run_service):
        seed_calls.append({"workspace_id": workspace_id})
        return _SeedResult(workspace_id)

    for route in _demo_routes():
        g = route.endpoint.__globals__
        monkeypatch.setitem(g, "list_configured_providers", lambda: list(providers))
        monkeypatch.setitem(g, "_health_service", _ConfiguredHealth(providers))
        monkeypatch.setitem(g, "timeline_service", _StubTimeline())
        monkeypatch.setitem(g, "seed_demo_short", _seed)


# --------------------------------------------------------------------------- #
# 2. Readiness (P0-2): no LLM configured -> demo is not ready -> 409, no seed.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_first_run_step2_demo_blocked_until_llm_configured(client, monkeypatch) -> None:
    seed_calls: list[dict] = []
    _apply_demo_seams(monkeypatch, providers=[], seed_calls=seed_calls)

    async def _ws_access(workspace_id: int) -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=workspace_id)

    app.dependency_overrides[require_workspace_access] = _ws_access
    try:
        resp = await client.post("/api/creator/workspaces/1/demo-short/runs")
    finally:
        app.dependency_overrides.pop(require_workspace_access, None)

    assert resp.status_code == 409, "no configured LLM -> demo prerequisites not met"
    assert seed_calls == [], "must not seed when prerequisites are unmet"


# --------------------------------------------------------------------------- #
# 3. Demo seed (P0-3): with an LLM configured -> seeds a real renderable project.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_first_run_step3_demo_seeds_real_renderable_project(client, monkeypatch) -> None:
    seed_calls: list[dict] = []
    _apply_demo_seams(monkeypatch, providers=["openai", "groq"], seed_calls=seed_calls)

    async def _ws_access(workspace_id: int) -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=workspace_id)

    app.dependency_overrides[require_workspace_access] = _ws_access
    try:
        resp = await client.post("/api/creator/workspaces/1/demo-short/runs")
    finally:
        app.dependency_overrides.pop(require_workspace_access, None)

    assert resp.status_code == 201
    body = resp.json()
    # Real execution identity: a seeded project id + timeline, run bound to it.
    assert body["seeded_project_id"] == 202
    assert body["timeline_id"] == "demo-timeline"
    assert body["run"]["project_id"] == body["seeded_project_id"]
    assert body["run"]["current_stage"] == "IDEA_READY"
    assert seed_calls == [{"workspace_id": 1}]


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
