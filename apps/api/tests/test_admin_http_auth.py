# pyright: reportMissingImports=false, reportAttributeAccessIssue=false

from importlib import import_module

from fastapi.testclient import TestClient

app = import_module("shorts_api.main").app
admin = import_module("shorts_api.routes.admin")


def _mock_health_payload() -> dict[str, object]:
    return {
        "status": "ok",
        "db": {"status": "up"},
        "redis": {"status": "up"},
        "uptime_seconds": 1,
    }


async def _mock_get_system_health() -> dict[str, object]:
    return _mock_health_payload()


def test_admin_endpoint_returns_401_without_admin_api_key(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret")
    monkeypatch.setenv("API_KEY", "global-secret")
    monkeypatch.setattr(admin.admin_service, "get_system_health", _mock_get_system_health)

    with TestClient(app) as client:
        response = client.get("/api/admin/health")

    assert response.status_code == 401
    assert response.json()["detail"] == "Admin access denied"


def test_admin_endpoint_returns_200_with_correct_admin_api_key(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret")
    monkeypatch.setenv("API_KEY", "global-secret")
    monkeypatch.setattr(admin.admin_service, "get_system_health", _mock_get_system_health)

    with TestClient(app) as client:
        response = client.get(
            "/api/admin/health",
            headers={"x-admin-key": "admin-secret"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_global_api_key_alone_does_not_grant_admin_access(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret")
    monkeypatch.setenv("API_KEY", "global-secret")
    monkeypatch.setattr(admin.admin_service, "get_system_health", _mock_get_system_health)

    with TestClient(app) as client:
        response = client.get(
            "/api/admin/health",
            headers={"x-api-key": "global-secret"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Admin access denied"
