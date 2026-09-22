import hashlib
import logging

import pytest
from creator_service.logging_config import JsonFormatter
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from shorts_api.app_factory import create_app
from shorts_api.auth import ApiKeyMiddleware, CurrentUser, get_current_user

from tests.auth_lookup_support import AuthDatabase, auth_db


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", [False, True])
async def test_request_audit_attributes_personal_keys_without_secrets(
    auth_db: AuthDatabase, caplog: pytest.LogCaptureFixture, middleware: bool
) -> None:
    # Given
    app = create_app()
    if not middleware:
        app.user_middleware = [item for item in app.user_middleware if item.cls is not ApiKeyMiddleware]

    @app.post("/api/creator/audit-probe")
    async def mutate(user: CurrentUser = Depends(get_current_user)) -> int:
        return user.user_id

    caplog.set_level(logging.INFO, logger="shorts_api.app_factory")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # When
        responses = [
            await client.post("/api/creator/audit-probe", headers=headers)
            for headers in (
                {"X-API-Key": "personal-one"},
                {"Authorization": "Bearer personal-two"},
                {"X-API-Key": "other-user"},
            )
        ]
    # Then
    assert [response.status_code for response in responses] == [200, 200, 200]
    records = [record for record in caplog.records if record.name == "shorts_api.app_factory"]
    assert [(getattr(record, "user_id", None), getattr(record, "key_id", None)) for record in records] == [
        (7, 71), (7, 72), (8, 81),
    ]
    assert [getattr(record, "workspace_id", None) for record in records] == [10, 10, 30]
    serialized = "\n".join(JsonFormatter("api").format(record) for record in records)
    for secret in ("personal-one", "personal-two", "other-user"):
        assert secret not in serialized
        assert hashlib.sha256(secret.encode()).hexdigest() not in serialized


@pytest.mark.asyncio
async def test_auth_database_error_keeps_credentials_out_of_logs(
    auth_db: AuthDatabase, caplog: pytest.LogCaptureFixture
) -> None:
    # Given
    secret = "personal-one"
    key_hash = hashlib.sha256(secret.encode()).hexdigest()
    auth_db.key_error = ConnectionError(f"query failed: {secret} {key_hash}")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # When
        response = await client.get("/api/creator/models", headers={"X-API-Key": secret})
    # Then
    assert response.status_code == 503
    records = [record for record in caplog.records if record.name.startswith("shorts_api.")]
    assert any(record.levelno == logging.ERROR for record in records)
    serialized = "\n".join(JsonFormatter("api").format(record) for record in records)
    assert secret not in serialized
    assert key_hash not in serialized
