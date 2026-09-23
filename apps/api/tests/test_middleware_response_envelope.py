import logging

import pytest
from creator_service.logging_config import JsonFormatter
from creator_service.project_service import project_service
from httpx import AsyncClient
from shorts_api.auth import _current_user_ctx
from shorts_api.lifecycle import shutdown_state

from tests.auth_lookup_support import AuthDatabase, auth_db  # noqa: F401
from tests.middleware_app_support import (
    ORIGIN, SECURITY_HEADERS, middleware_app, middleware_client,  # noqa: F401
)


@pytest.mark.parametrize("origin", [ORIGIN, "https://foreign.example.test"])
@pytest.mark.parametrize("case,expected,identity", [
    ("missing", 401, None), ("invalid", 401, None), ("revoked", 401, None),
    ("foreign_workspace", 404, None), ("no_membership", 404, None),
    ("db_key_failure", 503, None), ("db_membership_failure", 503, None),
    ("pool_failure", 503, None), ("success", 200, (7, 71, 10)),
    ("validation", 422, (7, 71, 10)), ("conflict", 409, (7, 71, 10)),
    ("foreign_project", 404, (7, 71, 10)), ("shutdown", 503, (7, 71, 10)),
    ("preflight", 200, None), ("preflight_method_error", 400, None),
])
async def test_actual_responses_have_one_safe_log_and_applicable_headers(
    middleware_client: AsyncClient, auth_db: AuthDatabase, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture, origin: str, case: str,
    expected: int, identity: tuple[int, int, int] | None,
) -> None:
    # Given: real routes and auth SQL; only the database failure seam is injected.
    caplog.set_level(logging.INFO, logger="shorts_api.app_factory")
    method = "GET"
    path = "/api/creator/projects"
    headers = {"Origin": origin, "Authorization": "Bearer synthetic-bearer-secret"}
    payload = {"json_script": {"token": "synthetic-body-secret"}}
    match case:
        case "missing":
            middleware_client.headers.clear()
            headers.pop("Authorization")
        case "invalid" | "revoked" | "no_membership":
            headers["X-API-Key"] = {
                "invalid": "synthetic-invalid-secret", "revoked": "revoked-key",
                "no_membership": "no-membership",
            }[case]
        case "foreign_workspace":
            headers["X-Workspace-Id"] = "30"
        case "db_key_failure":
            auth_db.key_error = ConnectionError("synthetic-database-secret")
        case "db_membership_failure":
            auth_db.membership_error = ConnectionError("synthetic-database-secret")
        case "pool_failure":
            async def unavailable_pool() -> None:
                raise ConnectionError("synthetic-pool-secret")

            monkeypatch.setattr("creator_service.db.get_pool", unavailable_pool)
        case "validation" | "conflict" | "foreign_project":
            method = "POST"
            project_id = 2 if case == "foreign_project" else 1
            path = f"/api/creator/projects/{project_id}/script/import-json"
            if case == "conflict":
                await project_service.db.update_project(1, {"status": "deleting"}, workspace_id=10)
                payload = {"json_script": "{}"}
        case "shutdown":
            monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
            monkeypatch.setattr(shutdown_state, "is_shutting_down", True)
        case "preflight" | "preflight_method_error":
            method = "OPTIONS"
            headers["Access-Control-Request-Method"] = "POST" if case == "preflight" else "INVALID"
            headers["Access-Control-Request-Headers"] = "content-type,x-api-key"
            if origin != ORIGIN:
                expected = 400
        case "success":
            pass
        case _:
            pytest.fail(f"Unhandled test case: {case}")
    # When
    response = await middleware_client.request(
        method, path, headers=headers, params={"token": "synthetic-query-secret"}, json=payload,
    )
    # Then: preserve HTTP/CORS semantics and only trust fully authorized identity.
    assert response.status_code == expected
    assert response.headers.get("access-control-allow-origin") == (ORIGIN if origin == ORIGIN else None)
    assert response.headers["access-control-allow-credentials"] == "true"
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get_list(name) == [value]
    records = [r for r in caplog.records if r.name == "shorts_api.app_factory"]
    assert len(records) == 1
    record = records[0]
    assert record.getMessage().startswith(f"{method} {path} {expected} ")
    assert (record.user_id, record.key_id, record.workspace_id) == (identity or (None, None, None))
    serialized = JsonFormatter("api").format(record)
    for secret in (
        "personal-one", "synthetic-bearer-secret", "synthetic-body-secret",
        "synthetic-query-secret", "synthetic-invalid-secret", "synthetic-database-secret",
        "synthetic-pool-secret", "revoked-key", "no-membership",
    ):
        assert secret not in serialized
        assert secret not in str(response.headers)
    assert shutdown_state.inflight_requests == 0
    assert _current_user_ctx.get() is None
