from __future__ import annotations

import fcntl
import json
import os
import shutil
import socket
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Final, Iterator, TypedDict

from .storage_policy import StorageLowWatermark

_LEASE_SECONDS: Final = 900


class _LeaseRecord(TypedDict):
    bytes: int
    hostname: str
    pid: int
    expires_at: float


def _lease_directory() -> Path:
    return Path(tempfile.gettempdir()) / ".media-byte-leases"


def _owner_is_live(record: _LeaseRecord) -> bool:
    if record["hostname"] != socket.gethostname():
        return record["expires_at"] > time.time()
    try:
        os.kill(record["pid"], 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _reserved_bytes(directory: Path) -> int:
    reserved = 0
    for path in directory.glob("*.lease"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = _LeaseRecord(
                bytes=int(raw["bytes"]), hostname=str(raw["hostname"]),
                pid=int(raw["pid"]), expires_at=float(raw["expires_at"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            if path.stat().st_mtime + _LEASE_SECONDS <= time.time():
                path.unlink(missing_ok=True)
            continue
        if _owner_is_live(record):
            reserved += record["bytes"]
        else:
            path.unlink(missing_ok=True)
    return reserved


@contextmanager
def temp_byte_lease(incoming_bytes: int, low_watermark_bytes: int) -> Iterator[None]:
    if low_watermark_bytes <= 0:
        yield
        return
    directory = _lease_directory()
    directory.mkdir(mode=0o700, exist_ok=True)
    lock_path = directory / "leases.lock"
    lease_path = directory / f"{uuid.uuid4().hex}.lease"
    with lock_path.open("a+", encoding="ascii") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        free_bytes = shutil.disk_usage(tempfile.gettempdir()).free
        reserved_bytes = _reserved_bytes(directory)
        if free_bytes - reserved_bytes - incoming_bytes < low_watermark_bytes:
            raise StorageLowWatermark(incoming_bytes=incoming_bytes, free_bytes=free_bytes)
        record = _LeaseRecord(
            bytes=incoming_bytes,
            hostname=socket.gethostname(),
            pid=os.getpid(),
            expires_at=time.time() + _LEASE_SECONDS,
        )
        lease_path.write_text(json.dumps(record), encoding="utf-8")
    try:
        yield
    finally:
        with lock_path.open("a+", encoding="ascii") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            lease_path.unlink(missing_ok=True)
