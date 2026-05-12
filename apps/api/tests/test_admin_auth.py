import asyncio
from importlib import import_module

import pytest
from fastapi import HTTPException

admin = import_module("shorts_api.routes.admin")


def test_require_admin_uses_constant_time_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    compare_called = False

    def _fake_compare_digest(provided: str, expected: str) -> bool:
        nonlocal compare_called
        compare_called = True
        return provided == expected

    monkeypatch.setenv("ADMIN_API_KEY", "expected-key")
    monkeypatch.setattr(admin.hmac, "compare_digest", _fake_compare_digest)

    asyncio.run(admin.require_admin("expected-key"))

    assert compare_called is True


def test_require_admin_rejects_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "expected-key")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(admin.require_admin("wrong-key"))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Admin access denied"
