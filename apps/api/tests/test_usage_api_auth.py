from __future__ import annotations

from fastapi.routing import APIRoute

from shorts_api.auth import get_api_key
from shorts_api.main import app


def test_usage_routes_require_api_key_dependency() -> None:
    usage_routes = {
        route.path: route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/creator/usage/")
    }

    assert "/api/creator/usage/workspace/{workspace_id}" in usage_routes
    assert "/api/creator/usage/run/{run_id}" in usage_routes

    for route in usage_routes.values():
        dependency_calls = [dependency.call for dependency in route.dependant.dependencies]
        assert get_api_key in dependency_calls
