"""Tests for central ServiceError → HTTP response mapping.

Verifies that the exception handler registered in app_factory correctly
translates each ServiceError subclass to the expected HTTP status code and
JSON body format.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from creator_domain.exceptions import (
    ConflictError,
    DataIntegrityError,
    NotFoundError,
    QuotaExceededError,
    ServiceError,
    ServiceUnavailableError,
    ValidationError,
    VersionConflictError,
)


@pytest.fixture()
def app_with_exception_routes():
    """Create a minimal FastAPI app that uses our exception handler and
    has routes that raise each exception type."""
    from shorts_api.app_factory import create_app

    app = create_app()

    from fastapi import APIRouter

    test_router = APIRouter()

    @test_router.get("/test/not-found")
    async def raise_not_found():
        raise NotFoundError("Run 42 not found")

    @test_router.get("/test/validation")
    async def raise_validation():
        raise ValidationError("Invalid input")

    @test_router.get("/test/conflict")
    async def raise_conflict():
        raise ConflictError("Stage conflict")

    @test_router.get("/test/version-conflict")
    async def raise_version_conflict():
        raise VersionConflictError(resource_id=7, expected_version=3, actual_version=5)

    @test_router.get("/test/quota")
    async def raise_quota():
        raise QuotaExceededError("Rate limit hit")

    @test_router.get("/test/unavailable")
    async def raise_unavailable():
        raise ServiceUnavailableError("Backend down")

    @test_router.get("/test/data-integrity")
    async def raise_data_integrity():
        raise DataIntegrityError("Corrupt JSON")

    @test_router.get("/test/base-service-error")
    async def raise_base():
        raise ServiceError("Something broke")

    app.include_router(test_router)
    return app


@pytest.mark.asyncio
class TestServiceExceptionHandler:
    """Each ServiceError subclass maps to the correct HTTP response."""

    @pytest.mark.parametrize(
        "path,expected_status,expected_detail",
        [
            ("/test/not-found", 404, "Run 42 not found"),
            ("/test/validation", 400, "Invalid input"),
            ("/test/conflict", 409, "Stage conflict"),
            ("/test/version-conflict", 409, "Version conflict for 7: expected 3, actual 5"),
            ("/test/quota", 429, "Rate limit hit"),
            ("/test/unavailable", 503, "Backend down"),
            ("/test/data-integrity", 500, "Corrupt JSON"),
            ("/test/base-service-error", 500, "Something broke"),
        ],
    )
    async def test_exception_mapping(
        self,
        app_with_exception_routes,
        path: str,
        expected_status: int,
        expected_detail: str,
    ) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app_with_exception_routes),
            base_url="http://test",
        ) as client:
            resp = await client.get(path)
            assert resp.status_code == expected_status
            body = resp.json()
            assert body["detail"] == expected_detail

    async def test_non_service_errors_still_500(
        self,
        app_with_exception_routes,
    ) -> None:
        """Non-ServiceError exceptions should still be caught by the global
        handler and return 500 with an opaque detail message."""
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/test/unexpected")
        async def raise_unexpected():
            raise RuntimeError("oops")

        app_with_exception_routes.include_router(router)

        async with AsyncClient(
            transport=ASGITransport(
                app=app_with_exception_routes,
                raise_app_exceptions=False,
            ),
            base_url="http://test",
        ) as client:
            resp = await client.get("/test/unexpected")
            assert resp.status_code == 500
            body = resp.json()
            assert body["detail"] == "Internal server error"
