import asyncio
import logging
from importlib import import_module


admin = import_module("shorts_api.routes.admin")


def test_admin_unstick_run_emits_audit_log(caplog) -> None:
    async def _fake_unstick_run(run_id: str):
        return {"ok": True, "run_id": run_id, "current_stage": "SCRIPT_REVIEW"}

    caplog.set_level(logging.WARNING, logger="admin.audit")

    original = admin.admin_service.unstick_run
    admin.admin_service.unstick_run = _fake_unstick_run
    try:
        result = asyncio.run(admin.admin_unstick_run("42"))
    finally:
        admin.admin_service.unstick_run = original

    assert result["ok"] is True
    assert "ADMIN_ACTION: unstick_run | run_id=42" in caplog.text


def test_admin_clear_cache_emits_audit_log(caplog) -> None:
    async def _fake_clear_cache(*, key_pattern: str | None = None, dry_run: bool = False):
        return {
            "ok": True,
            "deleted_keys": 0,
            "key_pattern": key_pattern or "cache:*",
            "dry_run": dry_run,
            "matched_keys": [],
        }

    caplog.set_level(logging.WARNING, logger="admin.audit")

    original = admin.admin_service.clear_cache
    admin.admin_service.clear_cache = _fake_clear_cache
    try:
        result = asyncio.run(admin.admin_clear_cache(key_pattern="cache:test:*", dry_run=True))
    finally:
        admin.admin_service.clear_cache = original

    assert result["ok"] is True
    assert "ADMIN_ACTION: cache_clear | key_pattern=cache:test:* | dry_run=True" in caplog.text
