# pyright: reportMissingImports=false

from collections.abc import Iterator, Sequence
from datetime import datetime, timezone

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from pydantic import BaseModel
from shorts_api.auth import CurrentUser, require_run_access
from shorts_api.main import app, runs_router


def _iter_api_routes(routes: Sequence[object]) -> list[APIRoute]:
    return [route for route in routes if isinstance(route, APIRoute)]


class StubRun(BaseModel):
    id: int
    project_id: int
    current_stage: str
    status: str = "running"
    model_defaults: dict[str, str] | None = None
    created_at: datetime
    updated_at: datetime


class StubSection(BaseModel):
    section_id: str
    text: str
    display_text: str | None = None
    type: str | None = "narration"
    speaker: str | None = None
    duration: float | None = None
    turn_kind: str | None = None
    visual_override: None = None


class StubDraft(BaseModel):
    structured_script: list[StubSection] | None = None


class StubRunService:
    def __init__(self) -> None:
        self.runs: dict[int, StubRun] = {}
        self.updated_defaults: list[dict[str, object]] = []

    async def get_run(self, run_id: int) -> StubRun | None:
        return self.runs.get(run_id)

    async def update_model_defaults(self, run_id: int, updates: dict[str, str]) -> StubRun:
        run = self.runs.get(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        next_defaults = {**(run.model_defaults or {}), **updates}
        updated = run.model_copy(update={"model_defaults": next_defaults})
        self.runs[run_id] = updated
        self.updated_defaults.append({"run_id": run_id, "updates": updates})
        return updated


class StubScriptService:
    def __init__(self) -> None:
        self.drafts: dict[int, StubDraft] = {}

    async def get_active_draft(self, run_id: int) -> StubDraft | None:
        return self.drafts.get(run_id)


class StubAudioArtifact(BaseModel):
    id: int
    section_id: str | None
    path: str


class StubAudioService:
    def __init__(self) -> None:
        self.paragraph_audio: dict[int, list[StubAudioArtifact]] = {}

    async def list_paragraph_audio(self, run_id: int) -> list[StubAudioArtifact]:
        return self.paragraph_audio.get(run_id, [])


class StubSubtitleService:
    async def list_paragraph_subtitles(self, run_id: int) -> list[object]:
        _ = run_id
        return []


class StubVisualPlanService:
    async def get_active_plan(self, run_id: int) -> None:
        _ = run_id
        return None


class StubVisualAssetService:
    async def list_by_run(self, run_id: int) -> dict[str, list[object]]:
        _ = run_id
        return {}


@pytest.fixture
def contract_services(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[StubRunService, StubScriptService, StubAudioService]]:
    run_svc = StubRunService()
    script_svc = StubScriptService()
    audio_svc = StubAudioService()

    task_counter = {"value": 0}

    def dispatch_audio(**kwargs: object) -> str:
        _ = kwargs
        task_counter["value"] += 1
        return f"audio-task-{task_counter['value']}"

    def dispatch_subtitles(**kwargs: object) -> str:
        _ = kwargs
        task_counter["value"] += 1
        return f"subtitle-task-{task_counter['value']}"

    def validate_model_key(model_key: str) -> None:
        _ = model_key

    def validate_model_defaults(model_defaults: dict[str, str] | None) -> None:
        _ = model_defaults

    for route in _iter_api_routes(runs_router.routes):
        if route.name in {
            "get_storyboard",
            "generate_all_paragraph_audio",
            "generate_all_paragraph_subtitles",
            "update_model_defaults",
        }:
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "script_service", script_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "audio_service", audio_svc)
            monkeypatch.setitem(
                route.endpoint.__globals__, "subtitle_service", StubSubtitleService()
            )
            monkeypatch.setitem(
                route.endpoint.__globals__, "visual_plan_service", StubVisualPlanService()
            )
            monkeypatch.setitem(
                route.endpoint.__globals__, "visual_asset_service", StubVisualAssetService()
            )
            monkeypatch.setitem(
                route.endpoint.__globals__, "dispatch_paragraph_audio", dispatch_audio
            )
            monkeypatch.setitem(
                route.endpoint.__globals__, "dispatch_paragraph_subtitles", dispatch_subtitles
            )
            monkeypatch.setitem(
                route.endpoint.__globals__, "validate_model_key", validate_model_key
            )
            monkeypatch.setitem(
                route.endpoint.__globals__, "validate_model_defaults", validate_model_defaults
            )

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, StubRun]:
        run = run_svc.runs.get(run_id)
        if run is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Run not found")
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    yield run_svc, script_svc, audio_svc

    app.dependency_overrides.pop(require_run_access, None)


def _seed_storyboard_data(
    run_svc: StubRunService, script_svc: StubScriptService, audio_svc: StubAudioService
) -> None:
    now = datetime.now(timezone.utc)
    run_svc.runs[101] = StubRun(
        id=101,
        project_id=1,
        current_stage="VISUAL_ASSET_REVIEW",
        created_at=now,
        updated_at=now,
    )
    script_svc.drafts[101] = StubDraft(
        structured_script=[
            StubSection(section_id="sec-1", text="line one"),
            StubSection(section_id="sec-2", text="line two"),
        ]
    )
    audio_svc.paragraph_audio[101] = [
        StubAudioArtifact(id=1, section_id="sec-1", path="/tmp/sec-1.wav"),
        StubAudioArtifact(id=2, section_id="sec-2", path="/tmp/sec-2.wav"),
    ]


@pytest.mark.asyncio
async def test_storyboard_response_contract(client, contract_services):
    run_svc, script_svc, audio_svc = contract_services
    _seed_storyboard_data(run_svc, script_svc, audio_svc)

    response = await client.get("/api/creator/runs/101/storyboard")
    assert response.status_code == 200
    body = response.json()

    assert set(body) == {
        "run_id",
        "paragraphs",
        "render_ready",
        "total_paragraphs",
        "ready_paragraphs",
    }
    assert body["run_id"] == 101
    assert isinstance(body["paragraphs"], list)
    assert body["total_paragraphs"] == 2

    paragraph = body["paragraphs"][0]
    assert set(paragraph) == {
        "section_id",
        "order",
        "text",
        "display_text",
        "image_prompt",
        "image_url",
        "audio_url",
        "audio_duration",
        "subtitles_url",
        "subtitle_entries",
        "status",
        "stale_flags",
        "scene_id",
        "image_asset_id",
        "audio_artifact_id",
        "subtitle_artifact_id",
        "section_type",
        "speaker",
        "duration",
        "turn_kind",
        "visual_override",
    }


@pytest.mark.asyncio
async def test_bulk_audio_dispatch_contract(client, contract_services):
    run_svc, script_svc, audio_svc = contract_services
    _seed_storyboard_data(run_svc, script_svc, audio_svc)
    # Clear pre-seeded audio so bulk dispatch actually enqueues tasks
    # (the endpoint now skips sections that already have audio).
    audio_svc.paragraph_audio.pop(101, None)

    response = await client.post("/api/creator/runs/101/storyboard/generate-all-audio", json={})
    assert response.status_code == 202
    body = response.json()

    assert set(body) == {"run_id", "tasks", "total", "failed"}
    assert body["run_id"] == 101
    assert body["total"] == 2
    assert isinstance(body["failed"], int)
    assert isinstance(body["tasks"], list)
    assert set(body["tasks"][0]) == {"section_id", "task_id"}


@pytest.mark.asyncio
async def test_bulk_subtitles_dispatch_contract(client, contract_services):
    run_svc, script_svc, audio_svc = contract_services
    _seed_storyboard_data(run_svc, script_svc, audio_svc)

    response = await client.post("/api/creator/runs/101/storyboard/generate-all-subtitles", json={})
    assert response.status_code == 202
    body = response.json()

    assert set(body) == {"run_id", "tasks", "total", "failed"}
    assert body["run_id"] == 101
    assert body["total"] == 2
    assert isinstance(body["tasks"], list)
    assert set(body["tasks"][0]) == {"section_id", "task_id"}


@pytest.mark.asyncio
async def test_healthz_contract(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_contract(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert "models" in body
    assert isinstance(body["models"], dict)


@pytest.mark.asyncio
async def test_settings_api_keys_contract(client):
    response = await client.get("/api/creator/settings/api-keys")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert all(set(item) == {"provider", "label", "configured"} for item in body)


@pytest.mark.asyncio
async def test_model_defaults_update_contract(client, contract_services):
    run_svc, script_svc, audio_svc = contract_services
    _ = (script_svc, audio_svc)
    now = datetime.now(timezone.utc)
    run_svc.runs[202] = StubRun(
        id=202,
        project_id=1,
        current_stage="SCRIPT_REVIEW",
        model_defaults={"script_model": "qwen3-4b"},
        created_at=now,
        updated_at=now,
    )

    response = await client.patch(
        "/api/creator/runs/202/model-defaults", json={"tts_model": "qwen3-tts"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 202
    assert body["model_defaults"] == {"script_model": "qwen3-4b", "tts_model": "qwen3-tts"}


@pytest.mark.asyncio
async def test_cors_preflight_contract(client):
    response = await client.options(
        "/api/creator/models",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5174"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_middleware_configured():
    cors_middleware = None
    for middleware in app.user_middleware:
        if middleware.cls is CORSMiddleware:
            cors_middleware = middleware
            break

    assert cors_middleware is not None
