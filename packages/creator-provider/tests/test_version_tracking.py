"""Tests for versioned asset version tracking."""

from __future__ import annotations

import pytest

from creator_provider.versioned_assets import (
    clear_loaded_asset_versions,
    get_loaded_asset_versions,
    get_prompt,
    get_schema,
    get_tool_definition,
)


@pytest.fixture(autouse=True)
def reset_tracking() -> None:
    """Reset version tracking before and after each test."""
    clear_loaded_asset_versions()
    # Clear lru_cache to avoid cached results from previous tests
    get_prompt.cache_clear()
    get_schema.cache_clear()
    get_tool_definition.cache_clear()
    yield
    clear_loaded_asset_versions()
    get_prompt.cache_clear()
    get_schema.cache_clear()
    get_tool_definition.cache_clear()


def test_get_prompt_records_version() -> None:
    """Test that get_prompt records asset version."""
    clear_loaded_asset_versions()
    get_prompt.cache_clear()

    result = get_prompt("sd_local_quality_prefix")
    assert isinstance(result, str)

    versions = get_loaded_asset_versions()
    assert "prompts/sd_local_quality_prefix" in versions
    assert versions["prompts/sd_local_quality_prefix"] == "v1"


def test_get_schema_records_version() -> None:
    """Test that get_schema records asset version."""
    clear_loaded_asset_versions()
    get_schema.cache_clear()

    result = get_schema("sd_local_image_request")
    assert isinstance(result, dict)

    versions = get_loaded_asset_versions()
    assert "schemas/sd_local_image_request" in versions
    assert versions["schemas/sd_local_image_request"] == "v1"


def test_get_tool_definition_records_version() -> None:
    """Test that get_tool_definition records asset version."""
    clear_loaded_asset_versions()
    get_tool_definition.cache_clear()

    result = get_tool_definition("llm_chat_message")
    assert isinstance(result, dict)

    versions = get_loaded_asset_versions()
    assert "tools/llm_chat_message" in versions
    assert versions["tools/llm_chat_message"] == "v1"


def test_get_loaded_asset_versions_returns_dict() -> None:
    """Test that get_loaded_asset_versions returns correct dict."""
    clear_loaded_asset_versions()
    get_prompt.cache_clear()
    get_schema.cache_clear()

    # Load some assets
    get_prompt("sd_local_quality_prefix")
    get_schema("sd_local_image_request")

    versions = get_loaded_asset_versions()
    assert isinstance(versions, dict)
    assert len(versions) == 2
    assert versions["prompts/sd_local_quality_prefix"] == "v1"
    assert versions["schemas/sd_local_image_request"] == "v1"


def test_clear_loaded_asset_versions_resets_dict() -> None:
    """Test that clear_loaded_asset_versions resets the dict."""
    clear_loaded_asset_versions()
    get_prompt.cache_clear()

    # Load an asset
    get_prompt("sd_local_quality_prefix")
    assert len(get_loaded_asset_versions()) > 0

    # Clear and verify
    clear_loaded_asset_versions()
    assert len(get_loaded_asset_versions()) == 0


def test_get_loaded_asset_versions_returns_snapshot() -> None:
    """Test that get_loaded_asset_versions returns a snapshot (not a reference)."""
    clear_loaded_asset_versions()
    get_prompt.cache_clear()

    get_prompt("sd_local_quality_prefix")

    snapshot1 = get_loaded_asset_versions()
    original_len = len(snapshot1)

    # Modify the snapshot
    snapshot1["fake/asset"] = "v1"

    # Load another asset
    get_schema.cache_clear()
    get_schema("sd_local_image_request")

    # Get a new snapshot
    snapshot2 = get_loaded_asset_versions()

    # The original snapshot should still have only the original asset
    assert len(snapshot1) == original_len + 1  # We added one
    # The new snapshot should have two assets
    assert len(snapshot2) == 2
    assert "fake/asset" not in snapshot2
