# pyright: reportMissingImports=false

from collections.abc import Sequence
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from pydantic import BaseModel
from pydantic import ValidationError
from shorts_api.auth import CurrentUser, require_run_access
from shorts_api.main import app
from shorts_api.main import runs_router
from shorts_api.routes.creator_runs_storyboard import (
    BulkParagraphAudioRequest,
    BulkParagraphSubtitlesRequest,
    ParagraphAudioRequest,
    ParagraphSubtitlesRequest,
)


def _iter_api_routes(routes: Sequence[object]) -> list[APIRoute]:
    return [route for route in routes if isinstance(route, APIRoute)]


class StubPipelineRun(BaseModel):
    id: int
    project_id: int
    current_stage: str
    status: str = "running"
    created_at: datetime
    updated_at: datetime


class StubRunService:
    def __init__(self) -> None:
        self.runs: dict[int, StubPipelineRun] = {}

    async def get_run(self, run_id: int, workspace_id: int | None = None) -> StubPipelineRun | None:
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


class StubTaskTrackingService:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, str]] = []

    async def record_task_queued(self, run_id: int, task_type: str, task_id: str) -> None:
        self.calls.append((run_id, task_type, task_id))


def _patch_storyboard_dispatch_and_tracking(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[dict[str, str | int]] | StubTaskTrackingService]:
    calls: dict[str, list[dict[str, str | int]] | StubTaskTrackingService] = {
        "audio": [],
        "subtitles": [],
        "tracking": StubTaskTrackingService(),
    }

    def _dispatch_paragraph_audio(run_id: int, section_id: str, tts_model: str, voice: str) -> str:
        audio_calls = calls["audio"]
        assert isinstance(audio_calls, list)
        audio_calls.append(
            {
                "run_id": run_id,
                "section_id": section_id,
                "tts_model": tts_model,
                "voice": voice,
            }
        )
        return f"audio-task-{section_id}"

    def _dispatch_paragraph_subtitles(
        run_id: int, section_id: str, subtitle_model: str, subtitle_format: str
    ) -> str:
        subtitle_calls = calls["subtitles"]
        assert isinstance(subtitle_calls, list)
        subtitle_calls.append(
            {
                "run_id": run_id,
                "section_id": section_id,
                "subtitle_model": subtitle_model,
                "subtitle_format": subtitle_format,
            }
        )
        return f"subtitle-task-{section_id}"

    for route in _iter_api_routes(runs_router.routes):
        if route.name in {
            "generate_paragraph_audio_endpoint",
            "generate_paragraph_subtitles_endpoint",
            "generate_all_paragraph_audio",
            "generate_all_paragraph_subtitles",
        }:
            monkeypatch.setitem(
                route.endpoint.__globals__, "dispatch_paragraph_audio", _dispatch_paragraph_audio
            )
            monkeypatch.setitem(
                route.endpoint.__globals__,
                "dispatch_paragraph_subtitles",
                _dispatch_paragraph_subtitles,
            )
    tracking = calls["tracking"]
    assert isinstance(tracking, StubTaskTrackingService)
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch.task_tracking_service.record_task_queued",
        tracking.record_task_queued,
    )

    return calls


def _patch_quota_functions(
    monkeypatch: pytest.MonkeyPatch,
    route_names: set[str],
    outcomes: list[tuple[bool, str]] | None = None,
) -> dict[str, list[tuple[int, str]]]:
    quota_calls: list[tuple[int, str]] = []
    cancel_calls: list[tuple[int, str]] = []
    results = list(outcomes or [])

    async def _check_workspace_quota(
        workspace_id: int, operation_type: str = "llm"
    ) -> tuple[bool, str]:
        quota_calls.append((workspace_id, operation_type))
        if results:
            return results.pop(0)
        return True, "ok"

    async def _cancel_workspace_quota_reservation(workspace_id: int, operation_type: str) -> None:
        cancel_calls.append((workspace_id, operation_type))

    for route in _iter_api_routes(runs_router.routes):
        if route.name in route_names:
            monkeypatch.setitem(
                route.endpoint.__globals__, "check_workspace_quota", _check_workspace_quota
            )
            monkeypatch.setitem(
                route.endpoint.__globals__,
                "cancel_workspace_quota_reservation",
                _cancel_workspace_quota_reservation,
            )

    monkeypatch.setattr(
        "creator_service.usage_service.check_workspace_quota",
        _check_workspace_quota,
    )
    monkeypatch.setattr(
        "shorts_api.routes.storyboard_dispatch.cancel_workspace_quota_reservation",
        _cancel_workspace_quota_reservation,
    )

    return {"quota": quota_calls, "cancel": cancel_calls}


@pytest.fixture
def stub_storyboard_services(monkeypatch: pytest.MonkeyPatch):
    run_svc = StubRunService()
    script_svc = StubScriptService()
    audio_svc = StubAudioService()

    monkeypatch.setattr("creator_service.run_service.run_service", run_svc)

    def fake_validate_model_key(model_key: str, expected_category: str | None = None) -> None:
        _ = expected_category
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
            monkeypatch.setitem(
                route.endpoint.__globals__, "validate_model_key", fake_validate_model_key
            )

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, StubPipelineRun]:
        run = run_svc.runs.get(run_id)
        if run is None:
            from fastapi import HTTPException as FastApiHTTPException

            raise FastApiHTTPException(status_code=404, detail="Run not found")
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    yield run_svc, script_svc, audio_svc

    app.dependency_overrides.pop(require_run_access, None)


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
    script_svc.drafts[10] = StubScriptDraft(
        structured_script=[StubSection(section_id="sec-1", text="hello")]
    )

    response = await client.post(
        "/api/creator/runs/10/storyboard/paragraphs/sec-1/generate-audio",
        json={"tts_model": "invalid-tts", "voice": "default"},
    )

    assert response.status_code == 400
    assert "Unknown model key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_paragraph_subtitles_rejects_invalid_subtitle_model(
    client, stub_storyboard_services
):
    run_svc, _script_svc, audio_svc = stub_storyboard_services
    run_svc.runs[11] = _make_run(11)
    audio_svc.by_section[(11, "sec-1")] = StubAudioArtifact(
        id=1, section_id="sec-1", path="/tmp/audio.wav"
    )

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
    script_svc.drafts[12] = StubScriptDraft(
        structured_script=[StubSection(section_id="sec-1", text="hello")]
    )

    response = await client.post(
        "/api/creator/runs/12/storyboard/generate-all-audio",
        json={"tts_model": "invalid-tts", "voice": "default"},
    )

    assert response.status_code == 400
    assert "Unknown model key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_all_subtitles_rejects_invalid_subtitle_model(
    client, stub_storyboard_services
):
    run_svc, _script_svc, audio_svc = stub_storyboard_services
    run_svc.runs[13] = _make_run(13)
    audio_svc.by_run[13] = [StubAudioArtifact(id=2, section_id="sec-1", path="/tmp/audio.wav")]

    response = await client.post(
        "/api/creator/runs/13/storyboard/generate-all-subtitles",
        json={"subtitle_model": "invalid-stt", "subtitle_format": "srt"},
    )

    assert response.status_code == 400
    assert "Unknown model key" in response.json()["detail"]


def test_storyboard_request_models_reject_overlong_strings() -> None:
    with pytest.raises(ValidationError):
        ParagraphAudioRequest(tts_model="x" * 257)
    with pytest.raises(ValidationError):
        ParagraphSubtitlesRequest(subtitle_model="x" * 257)
    with pytest.raises(ValidationError):
        BulkParagraphAudioRequest(voice="x" * 257)
    with pytest.raises(ValidationError):
        BulkParagraphSubtitlesRequest(subtitle_model="x" * 257)


@pytest.mark.asyncio
async def test_generate_paragraph_audio_checks_quota_before_dispatch(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, script_svc, _audio_svc = stub_storyboard_services
    run_svc.runs[20] = _make_run(20)
    script_svc.drafts[20] = StubScriptDraft(
        structured_script=[StubSection(section_id="sec-1", text="hi")]
    )
    calls = _patch_storyboard_dispatch_and_tracking(monkeypatch)
    quota = _patch_quota_functions(monkeypatch, {"generate_paragraph_audio_endpoint"})

    response = await client.post(
        "/api/creator/runs/20/storyboard/paragraphs/sec-1/generate-audio", json={}
    )

    assert response.status_code == 202
    assert quota["quota"] == [(1, "tts")]
    audio_calls = calls["audio"]
    assert isinstance(audio_calls, list)
    assert len(audio_calls) == 1


@pytest.mark.asyncio
async def test_generate_paragraph_subtitles_checks_quota_before_dispatch(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, _script_svc, audio_svc = stub_storyboard_services
    run_svc.runs[21] = _make_run(21)
    audio_svc.by_section[(21, "sec-1")] = StubAudioArtifact(
        id=1, section_id="sec-1", path="/tmp/a.wav"
    )
    calls = _patch_storyboard_dispatch_and_tracking(monkeypatch)
    quota = _patch_quota_functions(monkeypatch, {"generate_paragraph_subtitles_endpoint"})

    response = await client.post(
        "/api/creator/runs/21/storyboard/paragraphs/sec-1/generate-subtitles", json={}
    )

    assert response.status_code == 202
    assert quota["quota"] == [(1, "stt")]
    subtitle_calls = calls["subtitles"]
    assert isinstance(subtitle_calls, list)
    assert len(subtitle_calls) == 1


@pytest.mark.asyncio
async def test_generate_all_audio_checks_quota_per_paragraph(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, script_svc, _audio_svc = stub_storyboard_services
    run_svc.runs[22] = _make_run(22)
    script_svc.drafts[22] = StubScriptDraft(
        structured_script=[
            StubSection(section_id="sec-1", text="one"),
            StubSection(section_id="sec-2", text="two"),
        ]
    )
    calls = _patch_storyboard_dispatch_and_tracking(monkeypatch)
    quota = _patch_quota_functions(monkeypatch, {"generate_all_paragraph_audio"})

    response = await client.post("/api/creator/runs/22/storyboard/generate-all-audio", json={})

    assert response.status_code == 202
    assert quota["quota"] == [(1, "tts"), (1, "tts")]
    audio_calls = calls["audio"]
    assert isinstance(audio_calls, list)
    assert len(audio_calls) == 2


@pytest.mark.asyncio
async def test_generate_all_subtitles_checks_quota_per_paragraph(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, _script_svc, audio_svc = stub_storyboard_services
    run_svc.runs[23] = _make_run(23)
    audio_svc.by_run[23] = [
        StubAudioArtifact(id=1, section_id="sec-1", path="/tmp/1.wav"),
        StubAudioArtifact(id=2, section_id="sec-2", path="/tmp/2.wav"),
    ]
    calls = _patch_storyboard_dispatch_and_tracking(monkeypatch)
    quota = _patch_quota_functions(monkeypatch, {"generate_all_paragraph_subtitles"})

    response = await client.post("/api/creator/runs/23/storyboard/generate-all-subtitles", json={})

    assert response.status_code == 202
    assert quota["quota"] == [(1, "stt"), (1, "stt")]
    subtitle_calls = calls["subtitles"]
    assert isinstance(subtitle_calls, list)
    assert len(subtitle_calls) == 2


@pytest.mark.asyncio
async def test_generate_paragraph_audio_returns_429_when_quota_exhausted(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, script_svc, _audio_svc = stub_storyboard_services
    run_svc.runs[24] = _make_run(24)
    script_svc.drafts[24] = StubScriptDraft(
        structured_script=[StubSection(section_id="sec-1", text="hi")]
    )
    calls = _patch_storyboard_dispatch_and_tracking(monkeypatch)

    _patch_quota_functions(
        monkeypatch,
        {"generate_paragraph_audio_endpoint"},
        outcomes=[(False, "Monthly audio/render request quota exceeded")],
    )

    response = await client.post(
        "/api/creator/runs/24/storyboard/paragraphs/sec-1/generate-audio", json={}
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "Monthly audio/render request quota exceeded"
    audio_calls = calls["audio"]
    assert isinstance(audio_calls, list)
    assert len(audio_calls) == 0


@pytest.mark.asyncio
async def test_generate_paragraph_subtitles_returns_429_when_quota_exhausted(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, _script_svc, audio_svc = stub_storyboard_services
    run_svc.runs[25] = _make_run(25)
    audio_svc.by_section[(25, "sec-1")] = StubAudioArtifact(
        id=1, section_id="sec-1", path="/tmp/a.wav"
    )
    calls = _patch_storyboard_dispatch_and_tracking(monkeypatch)
    _patch_quota_functions(
        monkeypatch,
        {"generate_paragraph_subtitles_endpoint"},
        outcomes=[(False, "Monthly audio/render request quota exceeded")],
    )

    response = await client.post(
        "/api/creator/runs/25/storyboard/paragraphs/sec-1/generate-subtitles", json={}
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "Monthly audio/render request quota exceeded"
    subtitle_calls = calls["subtitles"]
    assert isinstance(subtitle_calls, list)
    assert len(subtitle_calls) == 0


@pytest.mark.asyncio
async def test_generate_all_audio_returns_429_when_quota_exhausted(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, script_svc, _audio_svc = stub_storyboard_services
    run_svc.runs[26] = _make_run(26)
    script_svc.drafts[26] = StubScriptDraft(
        structured_script=[
            StubSection(section_id="sec-1", text="one"),
            StubSection(section_id="sec-2", text="two"),
        ]
    )
    calls = _patch_storyboard_dispatch_and_tracking(monkeypatch)
    _patch_quota_functions(
        monkeypatch,
        {"generate_all_paragraph_audio"},
        outcomes=[(True, "ok"), (False, "Monthly audio/render request quota exceeded")],
    )

    response = await client.post("/api/creator/runs/26/storyboard/generate-all-audio", json={})

    assert response.status_code == 429
    assert response.json()["detail"] == "Monthly audio/render request quota exceeded"
    audio_calls = calls["audio"]
    assert isinstance(audio_calls, list)
    assert len(audio_calls) == 1


@pytest.mark.asyncio
async def test_generate_all_subtitles_returns_429_when_quota_exhausted(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, _script_svc, audio_svc = stub_storyboard_services
    run_svc.runs[27] = _make_run(27)
    audio_svc.by_run[27] = [
        StubAudioArtifact(id=1, section_id="sec-1", path="/tmp/1.wav"),
        StubAudioArtifact(id=2, section_id="sec-2", path="/tmp/2.wav"),
    ]
    calls = _patch_storyboard_dispatch_and_tracking(monkeypatch)
    _patch_quota_functions(
        monkeypatch,
        {"generate_all_paragraph_subtitles"},
        outcomes=[(True, "ok"), (False, "Monthly audio/render request quota exceeded")],
    )

    response = await client.post("/api/creator/runs/27/storyboard/generate-all-subtitles", json={})

    assert response.status_code == 429
    assert response.json()["detail"] == "Monthly audio/render request quota exceeded"
    subtitle_calls = calls["subtitles"]
    assert isinstance(subtitle_calls, list)
    assert len(subtitle_calls) == 1


@pytest.mark.asyncio
async def test_generate_paragraph_audio_cancels_reservation_when_dispatch_fails(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, script_svc, _audio_svc = stub_storyboard_services
    run_svc.runs[28] = _make_run(28)
    script_svc.drafts[28] = StubScriptDraft(
        structured_script=[StubSection(section_id="sec-1", text="hi")]
    )
    quota = _patch_quota_functions(monkeypatch, {"generate_paragraph_audio_endpoint"})

    def _raise_dispatch(*args, **kwargs):
        _ = (args, kwargs)
        raise RuntimeError("dispatch failure")

    for route in _iter_api_routes(runs_router.routes):
        if route.name == "generate_paragraph_audio_endpoint":
            monkeypatch.setitem(
                route.endpoint.__globals__, "dispatch_paragraph_audio", _raise_dispatch
            )

    response = await client.post(
        "/api/creator/runs/28/storyboard/paragraphs/sec-1/generate-audio", json={}
    )

    assert response.status_code == 503
    assert quota["cancel"] == [(1, "tts")]


@pytest.mark.asyncio
async def test_generate_paragraph_audio_cancels_reservation_when_tracking_fails(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, script_svc, _audio_svc = stub_storyboard_services
    run_svc.runs[29] = _make_run(29)
    script_svc.drafts[29] = StubScriptDraft(
        structured_script=[StubSection(section_id="sec-1", text="hi")]
    )
    _patch_storyboard_dispatch_and_tracking(monkeypatch)
    quota = _patch_quota_functions(monkeypatch, {"generate_paragraph_audio_endpoint"})

    class _FailingTrackingService:
        async def record_task_queued(self, run_id: int, task_type: str, task_id: str) -> None:
            _ = (run_id, task_type, task_id)
            raise RuntimeError("tracking failure")

    for route in _iter_api_routes(runs_router.routes):
        if route.name == "generate_paragraph_audio_endpoint":
            monkeypatch.setattr(
                "shorts_api.routes.storyboard_dispatch.task_tracking_service.record_task_queued",
                _FailingTrackingService().record_task_queued,
            )

    response = await client.post(
        "/api/creator/runs/29/storyboard/paragraphs/sec-1/generate-audio", json={}
    )

    assert response.status_code == 503
    assert quota["cancel"] == [(1, "tts")]


@pytest.mark.asyncio
async def test_generate_paragraph_subtitles_cancels_reservation_when_dispatch_fails(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, _script_svc, audio_svc = stub_storyboard_services
    run_svc.runs[30] = _make_run(30)
    audio_svc.by_section[(30, "sec-1")] = StubAudioArtifact(
        id=1, section_id="sec-1", path="/tmp/a.wav"
    )
    quota = _patch_quota_functions(monkeypatch, {"generate_paragraph_subtitles_endpoint"})

    def _raise_dispatch(*args, **kwargs):
        _ = (args, kwargs)
        raise RuntimeError("dispatch failure")

    for route in _iter_api_routes(runs_router.routes):
        if route.name == "generate_paragraph_subtitles_endpoint":
            monkeypatch.setitem(
                route.endpoint.__globals__, "dispatch_paragraph_subtitles", _raise_dispatch
            )

    response = await client.post(
        "/api/creator/runs/30/storyboard/paragraphs/sec-1/generate-subtitles", json={}
    )

    assert response.status_code == 503
    assert quota["cancel"] == [(1, "stt")]


@pytest.mark.asyncio
async def test_generate_paragraph_subtitles_cancels_reservation_when_tracking_fails(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, _script_svc, audio_svc = stub_storyboard_services
    run_svc.runs[31] = _make_run(31)
    audio_svc.by_section[(31, "sec-1")] = StubAudioArtifact(
        id=1, section_id="sec-1", path="/tmp/a.wav"
    )
    _patch_storyboard_dispatch_and_tracking(monkeypatch)
    quota = _patch_quota_functions(monkeypatch, {"generate_paragraph_subtitles_endpoint"})

    class _FailingTrackingService:
        async def record_task_queued(self, run_id: int, task_type: str, task_id: str) -> None:
            _ = (run_id, task_type, task_id)
            raise RuntimeError("tracking failure")

    for route in _iter_api_routes(runs_router.routes):
        if route.name == "generate_paragraph_subtitles_endpoint":
            monkeypatch.setattr(
                "shorts_api.routes.storyboard_dispatch.task_tracking_service.record_task_queued",
                _FailingTrackingService().record_task_queued,
            )

    response = await client.post(
        "/api/creator/runs/31/storyboard/paragraphs/sec-1/generate-subtitles", json={}
    )

    assert response.status_code == 503
    assert quota["cancel"] == [(1, "stt")]


@pytest.mark.asyncio
async def test_generate_all_audio_cancels_reservation_when_dispatch_fails(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, script_svc, _audio_svc = stub_storyboard_services
    run_svc.runs[32] = _make_run(32)
    script_svc.drafts[32] = StubScriptDraft(
        structured_script=[
            StubSection(section_id="sec-1", text="one"),
            StubSection(section_id="sec-2", text="two"),
        ]
    )
    quota = _patch_quota_functions(monkeypatch, {"generate_all_paragraph_audio"})

    def _dispatch_paragraph_audio(run_id: int, section_id: str, tts_model: str, voice: str) -> str:
        _ = (run_id, tts_model, voice)
        if section_id == "sec-2":
            raise RuntimeError("dispatch failure")
        return f"audio-task-{section_id}"

    for route in _iter_api_routes(runs_router.routes):
        if route.name == "generate_all_paragraph_audio":
            monkeypatch.setitem(
                route.endpoint.__globals__, "dispatch_paragraph_audio", _dispatch_paragraph_audio
            )

    response = await client.post("/api/creator/runs/32/storyboard/generate-all-audio", json={})

    assert response.status_code == 202
    assert quota["cancel"] == [(1, "tts")]


@pytest.mark.asyncio
async def test_generate_all_audio_cancels_reservation_when_tracking_fails(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, script_svc, _audio_svc = stub_storyboard_services
    run_svc.runs[33] = _make_run(33)
    script_svc.drafts[33] = StubScriptDraft(
        structured_script=[
            StubSection(section_id="sec-1", text="one"),
            StubSection(section_id="sec-2", text="two"),
        ]
    )
    _patch_storyboard_dispatch_and_tracking(monkeypatch)
    quota = _patch_quota_functions(monkeypatch, {"generate_all_paragraph_audio"})

    class _FailingTrackingService:
        async def record_task_queued(self, run_id: int, task_type: str, task_id: str) -> None:
            _ = (run_id, task_type)
            if task_id.endswith("sec-2"):
                raise RuntimeError("tracking failure")

    for route in _iter_api_routes(runs_router.routes):
        if route.name == "generate_all_paragraph_audio":
            monkeypatch.setattr(
                "shorts_api.routes.storyboard_dispatch.task_tracking_service.record_task_queued",
                _FailingTrackingService().record_task_queued,
            )

    response = await client.post("/api/creator/runs/33/storyboard/generate-all-audio", json={})

    assert response.status_code == 202
    assert quota["cancel"] == [(1, "tts")]


@pytest.mark.asyncio
async def test_generate_all_subtitles_cancels_reservation_when_dispatch_fails(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, _script_svc, audio_svc = stub_storyboard_services
    run_svc.runs[34] = _make_run(34)
    audio_svc.by_run[34] = [
        StubAudioArtifact(id=1, section_id="sec-1", path="/tmp/1.wav"),
        StubAudioArtifact(id=2, section_id="sec-2", path="/tmp/2.wav"),
    ]
    quota = _patch_quota_functions(monkeypatch, {"generate_all_paragraph_subtitles"})

    def _dispatch_paragraph_subtitles(
        run_id: int, section_id: str, subtitle_model: str, subtitle_format: str
    ) -> str:
        _ = (run_id, subtitle_model, subtitle_format)
        if section_id == "sec-2":
            raise RuntimeError("dispatch failure")
        return f"subtitle-task-{section_id}"

    for route in _iter_api_routes(runs_router.routes):
        if route.name == "generate_all_paragraph_subtitles":
            monkeypatch.setitem(
                route.endpoint.__globals__,
                "dispatch_paragraph_subtitles",
                _dispatch_paragraph_subtitles,
            )

    response = await client.post("/api/creator/runs/34/storyboard/generate-all-subtitles", json={})

    assert response.status_code == 202
    assert quota["cancel"] == [(1, "stt")]


@pytest.mark.asyncio
async def test_generate_all_subtitles_cancels_reservation_when_tracking_fails(
    client, stub_storyboard_services, monkeypatch: pytest.MonkeyPatch
):
    run_svc, _script_svc, audio_svc = stub_storyboard_services
    run_svc.runs[35] = _make_run(35)
    audio_svc.by_run[35] = [
        StubAudioArtifact(id=1, section_id="sec-1", path="/tmp/1.wav"),
        StubAudioArtifact(id=2, section_id="sec-2", path="/tmp/2.wav"),
    ]
    _patch_storyboard_dispatch_and_tracking(monkeypatch)
    quota = _patch_quota_functions(monkeypatch, {"generate_all_paragraph_subtitles"})

    class _FailingTrackingService:
        async def record_task_queued(self, run_id: int, task_type: str, task_id: str) -> None:
            _ = (run_id, task_type)
            if task_id.endswith("sec-2"):
                raise RuntimeError("tracking failure")

    for route in _iter_api_routes(runs_router.routes):
        if route.name == "generate_all_paragraph_subtitles":
            monkeypatch.setattr(
                "shorts_api.routes.storyboard_dispatch.task_tracking_service.record_task_queued",
                _FailingTrackingService().record_task_queued,
            )

    response = await client.post("/api/creator/runs/35/storyboard/generate-all-subtitles", json={})

    assert response.status_code == 202
    assert quota["cancel"] == [(1, "stt")]
