import importlib
import sys

import pytest
from httpx import ASGITransport, AsyncClient


def _load_app_module(monkeypatch: pytest.MonkeyPatch, *, environment: str, api_key: str | None):
    monkeypatch.setenv("ENVIRONMENT", environment)
    if api_key is None:
        monkeypatch.delenv("API_KEY", raising=False)
    else:
        monkeypatch.setenv("API_KEY", api_key)

    sys.modules.pop("shorts_api.main", None)
    return importlib.import_module("shorts_api.main")


@pytest.mark.asyncio
async def test_docs_endpoints_disabled_and_security_headers_in_production(
    monkeypatch: pytest.MonkeyPatch,
):
    main_module = _load_app_module(monkeypatch, environment="production", api_key="prod-secret-key")
    app = main_module.app

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        docs_response = await client.get("/docs")
        redoc_response = await client.get("/redoc")
        openapi_response = await client.get("/openapi.json")
        healthz_response = await client.get("/healthz")

    assert docs_response.status_code == 404
    assert redoc_response.status_code == 404
    assert openapi_response.status_code == 404

    assert healthz_response.status_code == 200
    assert healthz_response.headers.get("x-content-type-options") == "nosniff"
    assert healthz_response.headers.get("x-frame-options") == "DENY"
    assert healthz_response.headers.get("x-xss-protection") == "1; mode=block"
    assert (
        healthz_response.headers.get("strict-transport-security")
        == "max-age=31536000; includeSubDomains"
    )
    assert healthz_response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert (
        healthz_response.headers.get("permissions-policy")
        == "camera=(), microphone=(), geolocation=()"
    )


@pytest.mark.asyncio
async def test_docs_endpoints_accessible_without_api_key(monkeypatch: pytest.MonkeyPatch):
    main_module = _load_app_module(monkeypatch, environment="development", api_key=None)
    app = main_module.app

    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        docs_response = await client.get("/docs")
        redoc_response = await client.get("/redoc")
        openapi_response = await client.get("/openapi.json")

    assert docs_response.status_code == 200
    assert redoc_response.status_code == 200
    assert openapi_response.status_code == 200
