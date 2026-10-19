from __future__ import annotations

import fcntl
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .storage_policy import StorageLowWatermark


def _lease_directory() -> Path:
    return Path(tempfile.gettempdir()) / ".media-byte-leases"


def _reserved_bytes(directory: Path) -> int:
    return sum(
        int(path.read_text(encoding="ascii"))
        for path in directory.glob("*.lease")
    )


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
        lease_path.write_text(str(incoming_bytes), encoding="ascii")
    try:
        yield
    finally:
        with lock_path.open("a+", encoding="ascii") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            lease_path.unlink(missing_ok=True)
