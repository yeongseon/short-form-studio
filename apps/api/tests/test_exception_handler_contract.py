import pytest
from creator_service.error_redaction import JsonValue
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from shorts_api.app_factory import create_app
from starlette.exceptions import HTTPException as StarletteHTTPException


@pytest.mark.parametrize("exception_type", [HTTPException, StarletteHTTPException])
@pytest.mark.parametrize("status", [401, 404, 409, 422, 503])
async def test_exception_dispatch_preserves_status_and_protocol_headers(exception_type: type[StarletteHTTPException], status: int) -> None:
    # Given: supplemental dispatch test for headers absent from current real routes.
    app = create_app()
    headers = {"WWW-Authenticate": 'Bearer realm="studio"', "Retry-After": "30", "Allow": "GET", "X-Request-ID": "run_701"}

    @app.get("/test/error-contract")
    async def fail() -> None:
        raise exception_type(status, "Retry: Bearer syntheticPrivateValue", headers=headers)

    # When
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/test/error-contract")
    # Then
    assert response.status_code == status
    assert response.json() == {"detail": "Retry: <redacted>"}
    assert all(response.headers[name] == value for name, value in headers.items())


async def test_cyclic_and_unsupported_http_details_are_bounded() -> None:
    # Given
    app = create_app()
    cycle: list[JsonValue] = []
    cycle.append(cycle)

    class Opaque:
        def __str__(self) -> str:
            raise AssertionError("must not stringify")

    @app.get("/test/opaque-error")
    async def fail() -> None:
        raise HTTPException(422, {"cycle": cycle, "opaque": Opaque()})

    # When
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/test/opaque-error")
    # Then
    assert response.status_code == 422
    assert len(response.content) < 200
    assert response.json()["detail"]["opaque"] == "<unsupported>"


@pytest.mark.parametrize("status", [204, 304])
async def test_http_errors_keep_bodyless_status_semantics(status: int) -> None:
    # Given
    app = create_app()

    @app.get("/test/bodyless-error")
    async def fail() -> None:
        raise HTTPException(status, "synthetic detail", headers={"ETag": '"revision-701"'})

    # When
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/test/bodyless-error")
    # Then
    assert response.status_code == status
    assert response.content == b""
    assert response.headers["ETag"] == '"revision-701"'
