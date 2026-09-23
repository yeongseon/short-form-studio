import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from creator_service.project_service import InMemoryProjectStorage, project_service
from creator_service.workspace_service import InMemoryWorkspaceStorage, workspace_service
from httpx import ASGITransport, AsyncClient
from shorts_api.app_factory import create_app

from tests.auth_lookup_support import AuthDatabase, auth_db  # noqa: F401


@pytest.fixture
async def error_client(auth_db: AuthDatabase, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    projects = InMemoryProjectStorage()
    await projects.insert_project({"title": "Owned", "workspace_id": 10})
    await projects.insert_project({"title": "Foreign", "workspace_id": 30})
    workspaces = InMemoryWorkspaceStorage()
    await workspaces.add_member(10, 7)
    await workspaces.add_member(30, 8)
    monkeypatch.setattr(project_service, "db", projects)
    monkeypatch.setattr(workspace_service, "storage", workspaces)
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test",
        headers={"X-API-Key": "personal-one"},
    ) as client:
        yield client


@pytest.mark.parametrize("secret", [
    "gsk_syntheticPrivate_123456", "AIzaSyntheticPrivate_123456",
    "sk-proj-syntheticPrivate_123456_tail",
    "postgresql://synthetic:private-password@db.invalid/studio",
    "Bearer syntheticPrivateValue", "/home/synthetic/private/file.txt",
])
async def test_import_json_redacts_actual_parser_validation(error_client: AsyncClient, secret: str, caplog: pytest.LogCaptureFixture) -> None:
    # Given: actual parser emits a Pydantic error containing the invalid duration.
    script = json.dumps({"scenes": [{"text": "Safe narration", "duration": secret}]})
    # When
    response = await error_client.post("/api/creator/projects/1/script/import-json", json={"json_script": script})
    # Then
    assert response.status_code == 400
    assert secret not in response.text
    error = response.json()["detail"][0]
    assert error["type"] == "float_parsing"
    assert error["loc"] == ["duration"]
    assert error["input"] == "<redacted>"
    assert secret not in caplog.text


async def test_framework_422_redacts_nested_input_and_keeps_field_shape(error_client: AsyncClient) -> None:
    # Given: invalid request type includes a credential nested in the echoed input.
    value = {"token": "synthetic-opaque-value", "label": "Scene 1", "count": 3}
    # When
    response = await error_client.post("/api/creator/projects/1/script/import-json", json={"json_script": value})
    # Then
    assert response.status_code == 422
    assert response.json() == {"detail": [{
        "type": "string_type", "loc": ["body", "json_script"],
        "msg": "Input should be a valid string",
        "input": {"token": "<redacted>", "label": "Scene 1", "count": 3},
    }]}


async def test_safe_framework_422_keeps_original_api_shape(error_client: AsyncClient) -> None:
    # Given / When
    response = await error_client.post("/api/creator/projects/1/script/import-json", json={"json_script": 701})
    # Then
    assert response.status_code == 422
    assert response.json() == {"detail": [{
        "type": "string_type", "loc": ["body", "json_script"],
        "msg": "Input should be a valid string", "input": 701,
    }]}


@pytest.mark.parametrize("project_id", [2, 999])
async def test_foreign_and_missing_projects_remain_404(error_client: AsyncClient, project_id: int) -> None:
    # Given / When
    response = await error_client.post(f"/api/creator/projects/{project_id}/script/import-json", json={"json_script": "{}"})
    # Then
    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "invalid"}, {"X-API-Key": "revoked-key"}])
async def test_creator_auth_denies_before_error_detail(error_client: AsyncClient, headers: dict[str, str]) -> None:
    # Given
    error_client.headers.clear()
    # When
    response = await error_client.post("/api/creator/projects/1/script/import-json", headers=headers, json={"json_script": "{}"})
    # Then
    assert response.status_code == 401


async def test_db_failure_stays_503(error_client: AsyncClient, auth_db: AuthDatabase) -> None:
    # Given
    auth_db.key_error = ConnectionError("synthetic database failure")
    # When
    response = await error_client.post("/api/creator/projects/1/script/import-json", json={"json_script": "{}"})
    # Then
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}


async def test_actual_http_string_detail_keeps_actionable_label(error_client: AsyncClient) -> None:
    # Given / When
    response = await error_client.post("/api/creator/projects/1/script/import-json", json={
        "json_script": "{}", "model_defaults": {"render_profile": "Bearer syntheticPrivateValue"},
    })
    # Then
    assert response.status_code == 400
    assert response.json() == {"detail": "Unknown render profile '<redacted>'. Available profiles: ['fast_preview', 'high_quality', 'shorts_default']."}


async def test_import_markdown_redacts_caught_service_value_error(error_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: real route/ownership with a failure at its service boundary.
    monkeypatch.setattr("shorts_api.routes.creator_script.run_service.create_run", AsyncMock(
        side_effect=ValueError("Cannot save: gsk_syntheticPrivate_123456; retry"),
    ))
    # When
    response = await error_client.post("/api/creator/projects/1/script/import-markdown", json={"markdown": "## Scene\nSafe narration"})
    # Then
    assert response.status_code == 400
    assert response.json() == {"detail": "Cannot save: <redacted>; retry"}


async def test_actual_deleting_project_still_returns_conflict(error_client: AsyncClient) -> None:
    # Given
    await project_service.db.update_project(1, {"status": "deleting"}, workspace_id=10)
    # When
    response = await error_client.post("/api/creator/projects/1/script/import-json", json={"json_script": "{}"})
    # Then
    assert response.status_code == 409
    assert response.json() == {"detail": "Project is being deleted; cannot create new runs"}


async def test_large_framework_validation_input_is_bounded(error_client: AsyncClient) -> None:
    # Given / When
    response = await error_client.post("/api/creator/projects/1/script/import-json", json={"json_script": "x" * 500001})
    # Then
    assert response.status_code == 422
    assert len(response.content) < 500
    error = response.json()["detail"][0]
    assert error["loc"] == ["body", "json_script"]
    assert error["type"] == "string_too_long"
    assert error["ctx"] == {"max_length": 500000}
    assert error["input"] == "<redacted>"
