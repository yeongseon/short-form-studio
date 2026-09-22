import pytest
from asyncpg import InterfaceError, PostgresError
from httpx import ASGITransport, AsyncClient

from tests.auth_lookup_support import AuthDatabase, auth_db, identity_app


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_duplicate", [False, True])
async def test_memberships_fetched_once_when_key_authenticates(
    auth_db: AuthDatabase, fail_duplicate: bool
) -> None:
    # Given
    auth_db.fail_duplicate = fail_duplicate
    async with AsyncClient(transport=ASGITransport(app=identity_app()), base_url="http://test") as client:
        # When
        response = await client.get("/api/creator/identity", headers={"X-API-Key": "personal-one"})
    # Then
    assert response.status_code == 200
    assert auth_db.membership_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", [False, True])
@pytest.mark.parametrize("stage", ["key", "membership"])
@pytest.mark.parametrize("error_type", [PostgresError, InterfaceError, ConnectionError, TimeoutError, RuntimeError])
async def test_database_failure_returns_503_when_resolving_identity(
    auth_db: AuthDatabase, middleware: bool, stage: str, error_type: type[Exception]
) -> None:
    # Given
    error = error_type("database unavailable")
    if stage == "key":
        auth_db.key_error = error
    else:
        auth_db.membership_error = error
    app = identity_app(middleware=middleware)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        # When
        response = await client.get("/api/creator/identity", headers={"X-API-Key": "personal-one"})
    # Then
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", [False, True])
@pytest.mark.parametrize(
    "headers, expected",
    [
        ({}, 401),
        ({"X-API-Key": "invalid"}, 401),
        ({"X-API-Key": "revoked-key"}, 401),
        ({"X-API-Key": "no-membership"}, 404),
        ({"X-API-Key": "personal-one", "X-Workspace-Id": "30"}, 404),
        ({"X-API-Key": "personal-one", "X-Workspace-Id": "invalid"}, 404),
        ({"X-API-Key": "personal-one", "X-Workspace-Id": "20"}, 200),
    ],
)
async def test_access_boundary_when_credentials_or_workspace_change(
    auth_db: AuthDatabase, middleware: bool, headers: dict[str, str], expected: int
) -> None:
    # Given
    app = identity_app(middleware=middleware)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # When
        response = await client.get("/api/creator/identity", headers=headers)
    # Then
    assert response.status_code == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", [False, True])
async def test_personal_keys_resolve_distinct_ids_when_user_has_multiple_keys(
    auth_db: AuthDatabase, middleware: bool
) -> None:
    # Given
    app = identity_app(middleware=middleware)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # When
        responses = [
            await client.get("/api/creator/identity", headers=headers)
            for headers in (
                {"X-API-Key": "personal-one"},
                {"Authorization": "Bearer personal-two"},
                {"X-API-Key": "other-user"},
            )
        ]
    # Then
    assert [response.status_code for response in responses] == [200, 200, 200]
    assert [(response.json()["user_id"], response.json().get("key_id")) for response in responses] == [
        (7, 71), (7, 72), (8, 81),
    ]
