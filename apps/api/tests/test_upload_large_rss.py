import io
import json
import os
import resource
import struct
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from creator_service.media_asset_service import InMemoryMediaAssetStorage, MediaAssetService
from creator_service.object_storage import LocalStorageBackend
from shorts_api.auth import CurrentUser
from shorts_api.routes import creator_assets


class RecordingFile(io.BufferedReader):
    def __init__(self, path: Path) -> None:
        super().__init__(io.FileIO(path, "rb"))
        self.maximum = 0

    def read(self, size: int | None = -1) -> bytes:
        assert size is not None and 0 < size <= 65536, f"unbounded read: {size}"
        self.maximum = max(size, self.maximum)
        return super().read(size)


async def measure(root: Path, copies: int) -> None:
    service = MediaAssetService(LocalStorageBackend(str(root / "objects")), InMemoryMediaAssetStorage())
    creator_assets.media_asset_service = service
    source_path = root / "large.mp4"
    expected_size = source_path.stat().st_size
    baseline = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    async def upload() -> None:
        with RecordingFile(source_path) as source:
            file = UploadFile(source, filename="large.mp4", headers=Headers({"content-type": "video/mp4"}))
            asset = await creator_assets.upload_video_asset(7, file, CurrentUser(user_id=1, workspace_id=7))
            assert asset["width"] == 16 and asset["height"] == 24
            assert source.maximum == 65536

    async with anyio.create_task_group() as group:
        for _ in range(copies):
            group.start_soon(upload)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    page = await service.list_assets(workspace_id=7)
    assert page.total == copies
    assert all(asset.metadata["size_bytes"] == expected_size for asset in page.items)
    print(json.dumps({"delta_kib": peak - baseline, "peak_kib": peak, "bytes": expected_size, "copies": copies}))


@pytest.mark.parametrize("size_mib,copies", [(500, 1), (128, 5)])
def test_real_large_upload_has_bounded_rss(tmp_path: Path, size_mib: int, copies: int) -> None:
    # Given a valid small MP4 with a legal sparse free box, no huge bytes allocation.
    path = tmp_path / "large.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=16x24:d=0.2", str(path),
    ], check=True, timeout=30)
    target = size_mib * 1024 * 1024
    padding = target - path.stat().st_size
    with path.open("ab") as stream:
        stream.write(struct.pack(">I4s", padding, b"free"))
        stream.truncate(target)
    # When actual routes, probing, hashing and local storage run in a fresh process.
    result = subprocess.run(
        [sys.executable, __file__, str(tmp_path), str(copies)],
        capture_output=True, text=True, timeout=120, check=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    report = json.loads(result.stdout)
    # Then peak RSS growth stays far below a single allowed video allocation.
    assert report["delta_kib"] < 64 * 1024, report
    assert report["bytes"] == target
    assert report["copies"] == copies
    print(report)


if __name__ == "__main__":
    anyio.run(measure, Path(sys.argv[1]), int(sys.argv[2]))
