from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_ASSETS_ROOT = Path(__file__).resolve().parent


def _read_text_asset(asset_group: str, version: str, name: str, suffix: str) -> str:
    path = _ASSETS_ROOT / asset_group / version / f"{name}{suffix}"
    if not path.exists():
        raise FileNotFoundError(f"Asset not found: {path}")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def get_prompt(name: str, version: str = "v1") -> str:
    return _read_text_asset("prompts", version, name, ".txt")


@lru_cache(maxsize=None)
def get_schema(name: str, version: str = "v1") -> dict[str, Any]:
    raw = _read_text_asset("schemas", version, name, ".json")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Schema asset must be a JSON object: {name}")
    return data


@lru_cache(maxsize=None)
def get_tool_definition(name: str, version: str = "v1") -> dict[str, Any]:
    raw = _read_text_asset("tools", version, name, ".json")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Tool definition asset must be a JSON object: {name}")
    return data
