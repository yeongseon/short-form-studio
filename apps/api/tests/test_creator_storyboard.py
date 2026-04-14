# pyright: reportMissingImports=false

from collections.abc import Sequence
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from pydantic import BaseModel
from shorts_api.main import runs_router


def _iter_api_routes(routes: Sequence[object]) -> list[APIRoute]:
    return [route for route in routes if isinstance(route, APIRoute)]


class StubPipelineRun(BaseModel):
    id: int
    project_id: int
    current_stage: str
    status: str = "running"
    active_task_id: str | None = None
    created_at: datetime
    updated_at: datetime


class StubRunService:
    def __init__(self) -> None:
        self.runs: dict[int, StubPipelineRun] = {}

    async def get_run(self, run_id: int) -> StubPipelineRun | None:
        return self.runs.get(run_id)


class StubSection(BaseModel):
    section_id: str
    text: str


class StubScriptDraft(BaseModel):
    structured_script: list[StubSection] | None = None


class StubScriptService:
    def __init__(self) -> None:
        self.drafts: dict[int, StubScriptDraft] = {}

    async def get_active_draft(self, run_id: int) -> StubScriptDraft | None:
        return self.drafts.get(run_id)


class StubAudioArtifact(BaseModel):
    id: int
    section_id: str | None
    path: str


class StubAudioService:
    def __init__(self) -> None:
        self.by_section: dict[tuple[int, str], StubAudioArtifact] = {}
        self.by_run: dict[int, list[StubAudioArtifact]] = {}

    async def get_paragraph_audio(self, run_id: int, section_id: str) -> StubAudioArtifact | None:
        return self.by_section.get((run_id, section_id))

    async def list_paragraph_audio(self, run_id: int) -> list[StubAudioArtifact]:
        return self.by_run.get(run_id, [])


@pytest.fixture
def stub_storyboard_services(monkeypatch: pytest.MonkeyPatch):
    run_svc = StubRunService()
    script_svc = StubScriptService()
    audio_svc = StubAudioService()

    def fake_validate_model_key(model_key: str) -> None:
        if model_key.startswith("invalid"):
            raise HTTPException(status_code=400, detail=f"Unknown model key '{model_key}'")

    for route in _iter_api_routes(runs_router.routes):
        if route.name in {
            "generate_paragraph_audio_endpoint",
            "generate_paragraph_subtitles_endpoint",
            "generate_all_paragraph_audio",
            "generate_all_paragraph_subtitles",
        }:
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "script_service", script_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "audio_service", audio_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "validate_model_key", fake_validate_model_key)

    return run_svc, script_svc, audio_svc


def _make_run(run_id: int, stage: str = "VISUAL_ASSET_REVIEW") -> StubPipelineRun:
    now = datetime.now(timezone.utc)
    return StubPipelineRun(
        id=run_id,
        project_id=1,
        current_stage=stage,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_generate_paragraph_audio_rejects_invalid_tts_model(client, stub_storyboard_services):
    run_svc, script_svc, _audio_svc = stub_storyboard_services
    run_svc.runs[10] = _make_run(10)
    script_svc.drafts[10] = StubScriptDraft(structured_script=[StubSection(section_id="sec-1", text="hello")])

    response = await client.post(
        "/api/creator/runs/10/storyboard/paragraphs/sec-1/generate-audio",
        json={"tts_model": "invalid-tts", "voice": "default"},
    )

    assert response.status_code == 400
    assert "Unknown model key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_paragraph_subtitles_rejects_invalid_subtitle_model(client, stub_storyboard_services):
    run_svc, _script_svc, audio_svc = stub_storyboard_services
    run_svc.runs[11] = _make_run(11)
    audio_svc.by_section[(11, "sec-1")] = StubAudioArtifact(id=1, section_id="sec-1", path="/tmp/audio.wav")

    response = await client.post(
        "/api/creator/runs/11/storyboard/paragraphs/sec-1/generate-subtitles",
        json={"subtitle_model": "invalid-stt", "subtitle_format": "srt"},
    )

    assert response.status_code == 400
    assert "Unknown model key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_all_audio_rejects_invalid_tts_model(client, stub_storyboard_services):
    run_svc, script_svc, _audio_svc = stub_storyboard_services
    run_svc.runs[12] = _make_run(12)
    script_svc.drafts[12] = StubScriptDraft(structured_script=[StubSection(section_id="sec-1", text="hello")])

    response = await client.post(
        "/api/creator/runs/12/storyboard/generate-all-audio",
        json={"tts_model": "invalid-tts", "voice": "default"},
    )

    assert response.status_code == 400
    assert "Unknown model key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_all_subtitles_rejects_invalid_subtitle_model(client, stub_storyboard_services):
    run_svc, _script_svc, audio_svc = stub_storyboard_services
    run_svc.runs[13] = _make_run(13)
    audio_svc.by_run[13] = [StubAudioArtifact(id=2, section_id="sec-1", path="/tmp/audio.wav")]

    response = await client.post(
        "/api/creator/runs/13/storyboard/generate-all-subtitles",
        json={"subtitle_model": "invalid-stt", "subtitle_format": "srt"},
    )

    assert response.status_code == 400
    assert "Unknown model key" in response.json()["detail"]
