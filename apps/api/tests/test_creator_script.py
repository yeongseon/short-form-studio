# pyright: reportMissingImports=false

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Literal

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel
from shorts_api.routes.creator_script import router as script_router
from shorts_api.routes.creator_script import run_script_router


class StubProject(BaseModel):
    id: int
    title: str = "Test Project"


class StubPipelineRun(BaseModel):
    id: int
    project_id: int
    current_stage: str = "IDEA_READY"
    status: str = "pending"


class StubScriptDraft(BaseModel):
    id: int
    run_id: int
    source_type: Literal[
        "generated_by_model",
        "pasted_markdown",
        "uploaded_markdown",
        "edited_manually",
    ]
    markdown_content: str | None = None
    structured_script: list[object] | None = None
    version: int = 1
    created_at: datetime


class StubProjectService:
    def __init__(self) -> None:
        self.get_project_calls: list[int] = []
        self.projects: dict[int, StubProject] = {}

    async def get_project(self, project_id: int) -> StubProject | None:
        self.get_project_calls.append(project_id)
        return self.projects.get(project_id)


class StubRunService:
    def __init__(self) -> None:
        self.create_run_calls: list[dict[str, object]] = []
        self.raise_error_message: str | None = None
        self.next_run_id = 1

    async def create_run(
        self,
        project_id: int,
        model_defaults: dict[str, str] | None,
        style_preset: str,
        metadata: dict[str, object] | None = None,
        current_stage: str = "IDEA_READY",
        status: str = "pending",
    ) -> StubPipelineRun:
        if self.raise_error_message is not None:
            raise ValueError(self.raise_error_message)

        self.create_run_calls.append(
            {
                "project_id": project_id,
                "model_defaults": model_defaults,
                "style_preset": style_preset,
                "metadata": metadata,
                "current_stage": current_stage,
                "status": status,
            }
        )
        run = StubPipelineRun(
            id=self.next_run_id,
            project_id=project_id,
            current_stage=current_stage,
            status=status,
        )
        self.next_run_id += 1
        return run


class StubRunServiceRead:
    """Minimal run service stub for run-scoped endpoints (get_run only)."""

    def __init__(self) -> None:
        self.runs: dict[int, StubPipelineRun] = {}

    async def get_run(self, run_id: int) -> StubPipelineRun | None:
        return self.runs.get(run_id)

class StubScriptService:
    def __init__(self) -> None:
        self.save_draft_calls: list[dict[str, object]] = []
        self.raise_error_message: str | None = None
        self.next_draft_id = 1
        self.active_drafts: dict[int, StubScriptDraft] = {}

    async def get_active_draft(self, run_id: int) -> StubScriptDraft | None:
        return self.active_drafts.get(run_id)

    async def save_draft(
        self,
        run_id: int,
        source_type: Literal[
            "generated_by_model",
            "pasted_markdown",
            "uploaded_markdown",
            "edited_manually",
        ],
        markdown_content: str,
        structured_script: list | None = None,
    ) -> StubScriptDraft:
        if self.raise_error_message is not None:
            raise ValueError(self.raise_error_message)

        save_call: dict[str, object] = {
            "run_id": run_id,
            "source_type": source_type,
            "markdown_content": markdown_content,
        }
        if structured_script is not None:
            save_call["structured_script"] = structured_script
        self.save_draft_calls.append(save_call)
        current_draft = self.active_drafts.get(run_id)
        next_version = 1 if current_draft is None else current_draft.version + 1

        draft = StubScriptDraft(
            id=self.next_draft_id,
            run_id=run_id,
            source_type=source_type,
            markdown_content=markdown_content,
            structured_script=structured_script,
            version=next_version,
            created_at=datetime.now(timezone.utc),
        )
        self.next_draft_id += 1
        self.active_drafts[run_id] = draft
        return draft


def _iter_api_routes(routes: Sequence[object]) -> list[APIRoute]:
    return [route for route in routes if isinstance(route, APIRoute)]


@pytest.fixture
def stub_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubProjectService, StubRunService, StubScriptService]:
    project = StubProjectService()
    run = StubRunService()
    script = StubScriptService()

    for route in _iter_api_routes(script_router.routes):
        monkeypatch.setitem(route.endpoint.__globals__, "project_service", project)
        monkeypatch.setitem(route.endpoint.__globals__, "run_service", run)
        monkeypatch.setitem(route.endpoint.__globals__, "script_service", script)

    return project, run, script


@pytest.fixture
def stub_run_script_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunServiceRead, StubScriptService]:
    run = StubRunServiceRead()
    script = StubScriptService()

    for route in _iter_api_routes(run_script_router.routes):
        monkeypatch.setitem(route.endpoint.__globals__, "run_service", run)
        monkeypatch.setitem(route.endpoint.__globals__, "script_service", script)

    return run, script

@pytest.mark.asyncio
async def test_import_markdown_success(client, stub_services):
    project_service, run_service, script_service = stub_services
    project_service.projects[11] = StubProject(id=11, title="Project 11")

    response = await client.post(
        "/api/creator/projects/11/script/import-markdown",
        json={"markdown": "# My script\n\nHello world"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == 11
    assert body["run_id"] == 1
    assert body["draft"]["run_id"] == 1
    assert body["draft"]["source_type"] == "pasted_markdown"
    assert body["draft"]["markdown_content"] == "# My script\n\nHello world"
    assert project_service.get_project_calls == [11]
    assert run_service.create_run_calls == [
        {
            "project_id": 11,
            "model_defaults": None,
            "style_preset": "default",
            "metadata": None,
            "current_stage": "SCRIPT_REVIEW",
            "status": "running",
        }
    ]
    assert script_service.save_draft_calls == [
        {
            "run_id": 1,
            "source_type": "pasted_markdown",
            "markdown_content": "# My script\n\nHello world",
        }
    ]


@pytest.mark.asyncio
async def test_import_markdown_project_not_found(client, stub_services):
    _project_service, run_service, script_service = stub_services

    response = await client.post(
        "/api/creator/projects/404/script/import-markdown",
        json={"markdown": "# Missing project"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}
    assert run_service.create_run_calls == []
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_import_markdown_empty_markdown(client, stub_services):
    project_service, run_service, script_service = stub_services
    project_service.projects[7] = StubProject(id=7, title="Project 7")

    response = await client.post(
        "/api/creator/projects/7/script/import-markdown",
        json={"markdown": ""},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "markdown content must not be empty"}
    assert run_service.create_run_calls == []
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_import_markdown_with_model_defaults(client, stub_services):
    project_service, run_service, _script_service = stub_services
    project_service.projects[21] = StubProject(id=21, title="Project 21")

    response = await client.post(
        "/api/creator/projects/21/script/import-markdown",
        json={
            "markdown": "# Styled script",
            "model_defaults": {
                "script_model": "manual",
                "image_model": "sdxl-base",
                "tts_model": "edge-alloy",
            },
            "style_preset": "cinematic",
        },
    )

    assert response.status_code == 201
    assert run_service.create_run_calls == [
        {
            "project_id": 21,
            "model_defaults": {
                "script_model": "manual",
                "image_model": "sdxl-base",
                "tts_model": "edge-alloy",
            },
            "style_preset": "cinematic",
            "metadata": None,
            "current_stage": "SCRIPT_REVIEW",
            "status": "running",
        }
    ]


@pytest.mark.asyncio
async def test_import_markdown_missing_markdown_field(client, stub_services):
    project_service, _run_service, _script_service = stub_services
    project_service.projects[9] = StubProject(id=9, title="Project 9")

    response = await client.post(
        "/api/creator/projects/9/script/import-markdown",
        json={"style_preset": "default"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_import_markdown_service_error(client, stub_services):
    project_service, run_service, script_service = stub_services
    project_service.projects[15] = StubProject(id=15, title="Project 15")
    script_service.raise_error_message = "Invalid markdown structure"

    response = await client.post(
        "/api/creator/projects/15/script/import-markdown",
        json={"markdown": "# Broken"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid markdown structure"}
    assert run_service.create_run_calls == [
        {
            "project_id": 15,
            "model_defaults": None,
            "style_preset": "default",
            "metadata": None,
            "current_stage": "SCRIPT_REVIEW",
            "status": "running",
        }
    ]


@pytest.mark.asyncio
async def test_import_markdown_whitespace_only(client, stub_services):
    project_service, run_service, script_service = stub_services
    project_service.projects[7] = StubProject(id=7, title="Project 7")

    response = await client.post(
        "/api/creator/projects/7/script/import-markdown",
        json={"markdown": "   \n  \t  "},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "markdown content must not be empty"}
    assert run_service.create_run_calls == []
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_import_markdown_create_run_failure(client, stub_services):
    project_service, run_service, script_service = stub_services
    project_service.projects[20] = StubProject(id=20, title="Project 20")
    run_service.raise_error_message = "Duplicate run not allowed"

    response = await client.post(
        "/api/creator/projects/20/script/import-markdown",
        json={"markdown": "# Valid content"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Duplicate run not allowed"}
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_get_script_markdown_success(client, stub_run_script_services):
    run_service, script_service = stub_run_script_services
    run_service.runs[51] = StubPipelineRun(id=51, project_id=1)
    await script_service.save_draft(
        run_id=51,
        source_type="pasted_markdown",
        markdown_content="# Current script\n\nLine",
    )

    response = await client.get("/api/creator/runs/51/script/markdown")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": 51,
        "markdown": "# Current script\n\nLine",
        "version": 1,
    }

@pytest.mark.asyncio
async def test_get_script_markdown_no_draft(client, stub_run_script_services):
    run_service, _script_service = stub_run_script_services
    run_service.runs[999] = StubPipelineRun(id=999, project_id=1)

    response = await client.get("/api/creator/runs/999/script/markdown")

    assert response.status_code == 404
    assert response.json() == {"detail": "No script draft found for this run"}


@pytest.mark.asyncio
async def test_get_script_markdown_run_not_found(client, stub_run_script_services):
    _run_service, _script_service = stub_run_script_services

    response = await client.get("/api/creator/runs/888/script/markdown")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run 888 not found"}

@pytest.mark.asyncio
async def test_update_script_markdown_success(client, stub_run_script_services):
    run_service, script_service = stub_run_script_services
    run_service.runs[42] = StubPipelineRun(id=42, project_id=1)
    await script_service.save_draft(
        run_id=42,
        source_type="pasted_markdown",
        markdown_content="# V1",
    )

    response = await client.put(
        "/api/creator/runs/42/script/markdown",
        json={"markdown": "# V2\n\nUpdated"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 42
    assert body["draft"]["source_type"] == "edited_manually"
    assert body["draft"]["markdown_content"] == "# V2\n\nUpdated"
    assert body["draft"]["version"] == 2
    assert script_service.save_draft_calls[-1] == {
        "run_id": 42,
        "source_type": "edited_manually",
        "markdown_content": "# V2\n\nUpdated",
    }

@pytest.mark.asyncio
async def test_update_script_markdown_run_not_found(client, stub_run_script_services):
    _run_service, script_service = stub_run_script_services

    response = await client.put(
        "/api/creator/runs/77/script/markdown",
        json={"markdown": "# Fresh draft"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Run 77 not found"}
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_update_script_markdown_first_draft(client, stub_run_script_services):
    """PUT /markdown succeeds when run exists but no prior draft (creates first draft)."""
    run_service, script_service = stub_run_script_services
    run_service.runs[77] = StubPipelineRun(id=77, project_id=1)

    response = await client.put(
        "/api/creator/runs/77/script/markdown",
        json={"markdown": "# Fresh draft"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 77
    assert body["draft"]["version"] == 1
    assert body["draft"]["source_type"] == "edited_manually"
    assert body["draft"]["markdown_content"] == "# Fresh draft"
    assert script_service.active_drafts[77].version == 1

@pytest.mark.asyncio
async def test_update_script_markdown_empty(client, stub_run_script_services):
    _run_service, script_service = stub_run_script_services

    response = await client.put(
        "/api/creator/runs/13/script/markdown",
        json={"markdown": ""},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "markdown content must not be empty"}
    assert script_service.save_draft_calls == []

@pytest.mark.asyncio
async def test_update_script_markdown_whitespace_only(client, stub_run_script_services):
    _run_service, script_service = stub_run_script_services

    response = await client.put(
        "/api/creator/runs/13/script/markdown",
        json={"markdown": "   \n\t  "},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "markdown content must not be empty"}
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_get_script_structured_success(client, stub_run_script_services):
    run_service, script_service = stub_run_script_services
    run_service.runs[60] = StubPipelineRun(id=60, project_id=1)

    update_response = await client.put(
        "/api/creator/runs/60/script/structured",
        json={
            "sections": [
                {"section_id": "intro-1", "type": "intro", "text": "Welcome"},
                {"section_id": "body-1", "type": "body", "text": "Main point"},
            ]
        },
    )
    assert update_response.status_code == 200

    response = await client.get("/api/creator/runs/60/script/structured")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": 60,
        "sections": [
            {
                "section_id": "intro-1",
                "type": "intro",
                "text": "Welcome",
                "display_text": None,
                "speaker": "host",
                "duration": None,
                "turn_kind": None,
                "visual_override": None,
                "image_prompt": None,
                "mood": None,
                "composition": None,
                "style_tags": [],
            },
            {
                "section_id": "body-1",
                "type": "body",
                "text": "Main point",
                "display_text": None,
                "speaker": "host",
                "duration": None,
                "turn_kind": None,
                "visual_override": None,
                "image_prompt": None,
                "mood": None,
                "composition": None,
                "style_tags": [],
            },
        ],
        "version": 1,
    }
    assert script_service.active_drafts[60].structured_script is not None


@pytest.mark.asyncio
async def test_get_script_structured_no_draft(client, stub_run_script_services):
    run_service, _script_service = stub_run_script_services
    run_service.runs[61] = StubPipelineRun(id=61, project_id=1)

    response = await client.get("/api/creator/runs/61/script/structured")

    assert response.status_code == 404
    assert response.json() == {"detail": "No script draft found for this run"}


@pytest.mark.asyncio
async def test_get_script_structured_run_not_found(client, stub_run_script_services):
    _run_service, _script_service = stub_run_script_services

    response = await client.get("/api/creator/runs/404/script/structured")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run 404 not found"}


@pytest.mark.asyncio
async def test_get_script_structured_empty_sections(client, stub_run_script_services):
    run_service, script_service = stub_run_script_services
    run_service.runs[62] = StubPipelineRun(id=62, project_id=1)
    await script_service.save_draft(
        run_id=62,
        source_type="edited_manually",
        markdown_content="",
        structured_script=[],
    )

    response = await client.get("/api/creator/runs/62/script/structured")

    assert response.status_code == 200
    assert response.json() == {"run_id": 62, "sections": [], "version": 1}


@pytest.mark.asyncio
async def test_update_script_structured_success(client, stub_run_script_services):
    run_service, script_service = stub_run_script_services
    run_service.runs[63] = StubPipelineRun(id=63, project_id=1)

    response = await client.put(
        "/api/creator/runs/63/script/structured",
        json={
            "sections": [
                {"section_id": "sec-1", "type": "hook", "text": "Start here"},
                {"section_id": "sec-2", "type": "cta", "text": "Follow for more"},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 63
    assert body["draft"]["source_type"] == "edited_manually"
    assert body["draft"]["markdown_content"] == "## hook\n\nStart here\n\n## cta\n\nFollow for more"
    assert body["draft"]["structured_script"][0]["section_id"] == "sec-1"
    assert script_service.save_draft_calls[-1]["source_type"] == "edited_manually"
    assert script_service.save_draft_calls[-1]["markdown_content"] == "## hook\n\nStart here\n\n## cta\n\nFollow for more"


@pytest.mark.asyncio
async def test_update_script_structured_run_not_found(client, stub_run_script_services):
    _run_service, script_service = stub_run_script_services

    response = await client.put(
        "/api/creator/runs/64/script/structured",
        json={"sections": [{"section_id": "sec-1", "type": "hook", "text": "Start"}]},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Run 64 not found"}
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_update_script_structured_invalid_section(client, stub_run_script_services):
    run_service, script_service = stub_run_script_services
    run_service.runs[65] = StubPipelineRun(id=65, project_id=1)

    response = await client.put(
        "/api/creator/runs/65/script/structured",
        json={"sections": [{"type": "hook", "text": "Missing id"}]},
    )

    assert response.status_code == 400
    assert "detail" in response.json()
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_update_script_structured_preserves_section_id(client, stub_run_script_services):
    run_service, script_service = stub_run_script_services
    run_service.runs[66] = StubPipelineRun(id=66, project_id=1)

    response = await client.put(
        "/api/creator/runs/66/script/structured",
        json={
            "sections": [
                {"section_id": "original-101", "type": "intro", "text": "Hello"},
                {"section_id": "original-102", "type": "body", "text": "Details"},
            ]
        },
    )

    assert response.status_code == 200
    saved_sections = script_service.save_draft_calls[-1]["structured_script"]
    assert saved_sections is not None
    assert saved_sections[0].section_id == "original-101"
    assert saved_sections[1].section_id == "original-102"


# --- parse-markdown endpoint tests ---


class StubScriptSection:
    """Minimal stub matching ScriptSection interface for parse_markdown mock."""

    def __init__(self, section_id: str, type: str, text: str) -> None:
        self.section_id = section_id
        self.type = type
        self.text = text
        self.display_text = text
        self.speaker = "host"
        self.duration = None
        self.turn_kind = None
        self.visual_override = None

    def model_dump(self, *, mode: str = "python") -> dict:
        return {
            "section_id": self.section_id,
            "type": self.type,
            "text": self.text,
            "display_text": self.display_text,
            "speaker": self.speaker,
            "duration": self.duration,
            "turn_kind": self.turn_kind,
            "visual_override": self.visual_override,
        }


@pytest.fixture
def stub_parse_markdown_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunServiceRead, StubScriptService, list]:
    """Fixture that also patches parse_markdown for run_script_router routes."""
    run = StubRunServiceRead()
    script = StubScriptService()
    parse_calls: list[dict] = []

    def fake_parse_markdown(markdown: str, existing_sections=None):
        parse_calls.append({"markdown": markdown, "existing_sections": existing_sections})
        sections = []
        for line in markdown.split("\n"):
            if line.startswith("## "):
                heading = line[3:].strip().lower()
                sections.append(StubScriptSection(
                    section_id=f"{heading}-{len(sections)+1}",
                    type=heading,
                    text=f"Text for {heading}",
                ))
        if not sections:
            sections.append(StubScriptSection(
                section_id="body-1", type="body", text=markdown.strip()
            ))
        return sections

    for route in _iter_api_routes(run_script_router.routes):
        monkeypatch.setitem(route.endpoint.__globals__, "run_service", run)
        monkeypatch.setitem(route.endpoint.__globals__, "script_service", script)
        monkeypatch.setitem(route.endpoint.__globals__, "parse_markdown", fake_parse_markdown)

    return run, script, parse_calls


@pytest.mark.asyncio
async def test_parse_markdown_success(client, stub_parse_markdown_services):
    run_service, script_service, parse_calls = stub_parse_markdown_services
    run_service.runs[70] = StubPipelineRun(id=70, project_id=1)
    await script_service.save_draft(
        run_id=70,
        source_type="pasted_markdown",
        markdown_content="## Hook\n\nGreat opening\n\n## Body\n\nDetails",
    )

    response = await client.post("/api/creator/runs/70/script/parse-markdown")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 70
    assert len(body["sections"]) > 0
    assert body["version"] == 2  # new draft version saved
    assert len(parse_calls) == 1
    assert parse_calls[0]["markdown"] == "## Hook\n\nGreat opening\n\n## Body\n\nDetails"
    # Verify source_type is preserved from original draft (pasted_markdown, not edited_manually)
    assert script_service.save_draft_calls[-1]["source_type"] == "pasted_markdown"


@pytest.mark.asyncio
async def test_parse_markdown_run_not_found(client, stub_parse_markdown_services):
    _run_service, script_service, parse_calls = stub_parse_markdown_services

    response = await client.post("/api/creator/runs/999/script/parse-markdown")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run 999 not found"}
    assert script_service.save_draft_calls == []
    assert parse_calls == []


@pytest.mark.asyncio
async def test_parse_markdown_no_draft(client, stub_parse_markdown_services):
    run_service, script_service, parse_calls = stub_parse_markdown_services
    run_service.runs[71] = StubPipelineRun(id=71, project_id=1)

    response = await client.post("/api/creator/runs/71/script/parse-markdown")

    assert response.status_code == 404
    assert response.json() == {"detail": "No script draft found for this run"}
    assert script_service.save_draft_calls == []
    assert parse_calls == []


@pytest.mark.asyncio
async def test_parse_markdown_empty_content(client, stub_parse_markdown_services):
    run_service, script_service, parse_calls = stub_parse_markdown_services
    run_service.runs[72] = StubPipelineRun(id=72, project_id=1)
    await script_service.save_draft(
        run_id=72,
        source_type="pasted_markdown",
        markdown_content="",
    )

    response = await client.post("/api/creator/runs/72/script/parse-markdown")

    assert response.status_code == 400
    assert response.json() == {"detail": "Draft has no markdown content to parse"}
    assert parse_calls == []


@pytest.mark.asyncio
async def test_parse_markdown_whitespace_only_content(client, stub_parse_markdown_services):
    run_service, script_service, parse_calls = stub_parse_markdown_services
    run_service.runs[73] = StubPipelineRun(id=73, project_id=1)
    await script_service.save_draft(
        run_id=73,
        source_type="pasted_markdown",
        markdown_content="   \n  \t  ",
    )

    response = await client.post("/api/creator/runs/73/script/parse-markdown")

    assert response.status_code == 400
    assert response.json() == {"detail": "Draft has no markdown content to parse"}
    assert parse_calls == []


@pytest.mark.asyncio
async def test_parse_markdown_preserves_existing_sections(client, stub_parse_markdown_services):
    """Parse passes existing structured_script to parse_markdown for stable IDs."""
    run_service, script_service, parse_calls = stub_parse_markdown_services
    run_service.runs[74] = StubPipelineRun(id=74, project_id=1)

    existing_sections = [
        StubScriptSection(section_id="existing-1", type="hook", text="Old hook"),
    ]
    await script_service.save_draft(
        run_id=74,
        source_type="edited_manually",
        markdown_content="## Hook\n\nOld hook",
        structured_script=existing_sections,
    )

    response = await client.post("/api/creator/runs/74/script/parse-markdown")

    assert response.status_code == 200
    assert len(parse_calls) == 1
    # Verify existing_sections was passed to parse_markdown
    assert parse_calls[0]["existing_sections"] is not None
    assert parse_calls[0]["existing_sections"][0].section_id == "existing-1"


@pytest.mark.asyncio
async def test_parse_markdown_none_content(client, stub_parse_markdown_services):
    """Draft with markdown_content=None should return 400."""
    run_service, script_service, parse_calls = stub_parse_markdown_services
    run_service.runs[75] = StubPipelineRun(id=75, project_id=1)
    script_service.active_drafts[75] = StubScriptDraft(
        id=100,
        run_id=75,
        source_type="edited_manually",
        markdown_content=None,
        version=1,
        created_at=datetime.now(timezone.utc),
    )

    response = await client.post("/api/creator/runs/75/script/parse-markdown")

    assert response.status_code == 400
    assert response.json() == {"detail": "Draft has no markdown content to parse"}
    assert parse_calls == []
