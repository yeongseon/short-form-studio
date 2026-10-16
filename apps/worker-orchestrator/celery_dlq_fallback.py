from __future__ import annotations

import json
import os
import fcntl
from pathlib import Path

from creator_service.error_redaction import JsonValue


def append_fallback_entry(path: Path, entry: JsonValue, *, max_bytes: int) -> None:
    encoded = (json.dumps(entry, allow_nan=False) + "\n").encode()
    if len(encoded) > max_bytes:
        raise ValueError("DLQ fallback entry exceeds retention limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(f"{path.suffix}.lock")
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if path.exists() and path.stat().st_size + len(encoded) > max_bytes:
            rotated = path.with_suffix(f"{path.suffix}.1")
            os.replace(path, rotated)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def read_fallback_entries(path: Path, *, limit: int) -> list[dict[str, JsonValue]]:
    sources = [path.with_suffix(f"{path.suffix}.1"), path]
    entries: list[dict[str, JsonValue]] = []
    for source in sources:
        if not source.exists():
            continue
        with source.open(encoding="utf-8") as fallback_file:
            for line in fallback_file:
                try:
                    decoded = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    entries.append(decoded)
    return entries[-limit:]
