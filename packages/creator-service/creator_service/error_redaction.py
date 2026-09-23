"""Bound untrusted diagnostics and convert them to redacted JSON primitives."""

from __future__ import annotations

import math
import re
from itertools import islice
from typing import Final, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

_ABS_POSIX_PATH = re.compile(r"(?:/[\w.\-]+){2,}/?")
_WORKSPACE_PATH = re.compile(r"\bworkspaces/[\w./\-]+")
_WINDOWS_PATH = re.compile(r"[A-Za-z]:\\[\\\w.\- ]+")
_URL = re.compile(r"\bhttps?://[^\s'\"]+")
_CREDENTIAL_URI = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/'\"<>]*@[^\s;'\"<>]+")
_BEARER = re.compile(r"\bBearer[ \t]+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE)
_TOKEN_PREFIX = re.compile(r"\b(?:(?:sk|gsk|ghp|xoxb)[-_]|AKIA|AIza)[A-Za-z0-9_\-]{6,}")
_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{20,}\b")
_REDACTED: Final = "<redacted>"
_MAX_STRING: Final = 1024
_MAX_INPUT: Final = 8192
_MAX_ITEMS: Final = 50
_MAX_NODES: Final = 1000
_SENSITIVE_KEYS: Final = frozenset({"key", "secret", "token", "password", "credential"})


def redact_error_message(text: str) -> str:
    # Reject oversized text before regex processing; truncating first can split a secret.
    if len(text) > _MAX_INPUT:
        return _REDACTED
    redacted = _CREDENTIAL_URI.sub(_REDACTED, text)
    redacted = _URL.sub(_REDACTED, redacted)
    redacted = _BEARER.sub(_REDACTED, redacted)
    redacted = _TOKEN_PREFIX.sub(_REDACTED, redacted)
    redacted = _WINDOWS_PATH.sub(_REDACTED, redacted)
    redacted = _WORKSPACE_PATH.sub(_REDACTED, redacted)
    redacted = _ABS_POSIX_PATH.sub(_REDACTED, redacted)
    return _LONG_HEX.sub(_REDACTED, redacted)[:_MAX_STRING]


def sanitize_error_json(data: object, depth: int = 0) -> JsonValue:
    """Accept arbitrary boundary input, never invoking object stringification hooks.

    Only exact built-in containers/primitives are traversed. Unsupported objects
    (including subclasses with custom hooks) become opaque. A global node budget
    bounds branching as well as depth; cycles terminate at the same depth limit.
    """
    remaining = _MAX_NODES

    def visit(value: object, level: int) -> JsonValue:
        nonlocal remaining
        if level > 10:
            return "<nested>"
        if remaining <= 0:
            return "<truncated>"
        remaining -= 1
        match value:
            case None | bool():
                return value
            case str() if type(value) is str:
                return redact_error_message(value)
            case int() if type(value) is int:
                return value if value.bit_length() <= 256 else "<unsupported>"
            case float() if type(value) is float:
                return value if math.isfinite(value) else "<unsupported>"
            case dict() if type(value) is dict:
                result: dict[str, JsonValue] = {}
                for key, item in islice(value.items(), _MAX_ITEMS):
                    if remaining <= 0:
                        break
                    # Non-string keys are omitted, never passed to str/repr or JSON.
                    if not isinstance(key, str) or type(key) is not str:
                        continue
                    safe_key = redact_error_message(key)
                    sensitive = any(part in key.lower() for part in _SENSITIVE_KEYS)
                    result[safe_key] = _REDACTED if sensitive else visit(item, level + 1)
                return result
            case list() | tuple() if type(value) in (list, tuple):
                return [visit(item, level + 1) for item in value[:_MAX_ITEMS] if remaining > 0]
            case _:
                return "<unsupported>"

    return visit(data, depth)
