from __future__ import annotations

import json
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import cast


_ASSETS_ROOT = Path(__file__).resolve().parent

_loaded_assets_ctx: ContextVar[dict[str, str]] = ContextVar("loaded_assets", default={})


def _read_text_asset(asset_group: str, version: str, name: str, suffix: str) -> str:
    path = _ASSETS_ROOT / asset_group / version / f"{name}{suffix}"
    if not path.exists():
        raise FileNotFoundError(f"Asset not found: {path}")
    return path.read_text(encoding="utf-8")


def _track_loaded_asset(asset_group: str, version: str, name: str) -> None:
    loaded_assets = dict(_loaded_assets_ctx.get())
    loaded_assets[f"{asset_group}/{name}"] = version
    _ = _loaded_assets_ctx.set(loaded_assets)


def get_loaded_asset_versions() -> dict[str, str]:
    return dict(_loaded_assets_ctx.get())


def clear_loaded_asset_versions() -> None:
    _ = _loaded_assets_ctx.set({})


@lru_cache(maxsize=None)
def _get_prompt_cached(name: str, version: str) -> str:
    return _read_text_asset("prompts", version, name, ".txt")


def get_prompt(name: str, version: str = "v1") -> str:
    _track_loaded_asset("prompts", version, name)
    return _get_prompt_cached(name, version)


@lru_cache(maxsize=None)
def _get_schema_cached(name: str, version: str) -> dict[str, object]:
    raw = _read_text_asset("schemas", version, name, ".json")
    data = cast(object, json.loads(raw))
    if not isinstance(data, dict):
        raise ValueError(f"Schema asset must be a JSON object: {name}")
    return cast(dict[str, object], data)


def get_schema(name: str, version: str = "v1") -> dict[str, object]:
    _track_loaded_asset("schemas", version, name)
    return _get_schema_cached(name, version)


@lru_cache(maxsize=None)
def _get_tool_definition_cached(name: str, version: str) -> dict[str, object]:
    raw = _read_text_asset("tools", version, name, ".json")
    data = cast(object, json.loads(raw))
    if not isinstance(data, dict):
        raise ValueError(f"Tool definition asset must be a JSON object: {name}")
    return cast(dict[str, object], data)


def get_tool_definition(name: str, version: str = "v1") -> dict[str, object]:
    _track_loaded_asset("tools", version, name)
    return _get_tool_definition_cached(name, version)


def clear_asset_caches() -> None:
    _get_prompt_cached.cache_clear()
    _get_schema_cached.cache_clear()
    _get_tool_definition_cached.cache_clear()
