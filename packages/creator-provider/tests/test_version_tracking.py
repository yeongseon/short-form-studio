"""Tests for versioned asset version tracking."""

from __future__ import annotations

import asyncio
from collections.abc import Generator

import pytest

from creator_provider.versioned_assets import (
    clear_asset_caches,
    clear_loaded_asset_versions,
    get_loaded_asset_versions,
    get_prompt,
    get_schema,
    get_tool_definition,
)


@pytest.fixture(autouse=True)
def reset_tracking() -> Generator[None, None, None]:
    """Reset version tracking before and after each test."""
    clear_loaded_asset_versions()
    # Clear lru_cache to avoid cached results from previous tests
    clear_asset_caches()
    yield
    clear_loaded_asset_versions()
    clear_asset_caches()


def test_get_prompt_records_version() -> None:
    """Test that get_prompt records asset version."""
    clear_loaded_asset_versions()
    clear_asset_caches()

    result = get_prompt("sd_local_quality_prefix")
    assert isinstance(result, str)

    versions = get_loaded_asset_versions()
    assert "prompts/sd_local_quality_prefix" in versions
    assert versions["prompts/sd_local_quality_prefix"] == "v1"


def test_get_schema_records_version() -> None:
    """Test that get_schema records asset version."""
    clear_loaded_asset_versions()
    clear_asset_caches()

    result = get_schema("sd_local_image_request")
    assert isinstance(result, dict)

    versions = get_loaded_asset_versions()
    assert "schemas/sd_local_image_request" in versions
    assert versions["schemas/sd_local_image_request"] == "v1"


def test_get_tool_definition_records_version() -> None:
    """Test that get_tool_definition records asset version."""
    clear_loaded_asset_versions()
    clear_asset_caches()

    result = get_tool_definition("llm_chat_message")
    assert isinstance(result, dict)

    versions = get_loaded_asset_versions()
    assert "tools/llm_chat_message" in versions
    assert versions["tools/llm_chat_message"] == "v1"


def test_get_loaded_asset_versions_returns_dict() -> None:
    """Test that get_loaded_asset_versions returns correct dict."""
    clear_loaded_asset_versions()
    clear_asset_caches()

    # Load some assets
    _ = get_prompt("sd_local_quality_prefix")
    _ = get_schema("sd_local_image_request")

    versions = get_loaded_asset_versions()
    assert isinstance(versions, dict)
    assert len(versions) == 2
    assert versions["prompts/sd_local_quality_prefix"] == "v1"
    assert versions["schemas/sd_local_image_request"] == "v1"


def test_clear_loaded_asset_versions_resets_dict() -> None:
    """Test that clear_loaded_asset_versions resets the dict."""
    clear_loaded_asset_versions()
    clear_asset_caches()

    # Load an asset
    _ = get_prompt("sd_local_quality_prefix")
    assert len(get_loaded_asset_versions()) > 0

    # Clear and verify
    clear_loaded_asset_versions()
    assert len(get_loaded_asset_versions()) == 0


def test_get_loaded_asset_versions_returns_snapshot() -> None:
    """Test that get_loaded_asset_versions returns a snapshot (not a reference)."""
    clear_loaded_asset_versions()
    clear_asset_caches()

    _ = get_prompt("sd_local_quality_prefix")

    snapshot1 = get_loaded_asset_versions()
    original_len = len(snapshot1)

    # Modify the snapshot
    snapshot1["fake/asset"] = "v1"

    # Load another asset
    clear_asset_caches()
    _ = get_schema("sd_local_image_request")

    # Get a new snapshot
    snapshot2 = get_loaded_asset_versions()

    # The original snapshot should still have only the original asset
    assert len(snapshot1) == original_len + 1  # We added one
    # The new snapshot should have two assets
    assert len(snapshot2) == 2
    assert "fake/asset" not in snapshot2


def test_loaded_versions_isolated_per_async_context() -> None:
    async def worker_prompt() -> dict[str, str]:
        clear_loaded_asset_versions()
        _ = get_prompt("sd_local_quality_prefix")
        await asyncio.sleep(0)
        return get_loaded_asset_versions()

    async def worker_prompt_again() -> dict[str, str]:
        clear_loaded_asset_versions()
        _ = get_prompt("sd_local_quality_prefix")
        await asyncio.sleep(0)
        return get_loaded_asset_versions()

    async def run_workers() -> tuple[dict[str, str], dict[str, str]]:
        return await asyncio.gather(worker_prompt(), worker_prompt_again())

    prompt_versions, second_prompt_versions = asyncio.run(run_workers())
    assert "prompts/sd_local_quality_prefix" in prompt_versions
    assert "prompts/sd_local_quality_prefix" in second_prompt_versions
