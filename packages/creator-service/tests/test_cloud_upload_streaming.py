import io
from types import SimpleNamespace

import pytest

from creator_service.object_storage import AzureBlobStorageBackend, S3StorageBackend


class BoundedSource(io.BytesIO):
    def read(self, size: int | None = -1) -> bytes:
        assert size is not None and 0 < size <= 64 * 1024
        return super().read(size)


@pytest.mark.parametrize("backend_type", [S3StorageBackend, AzureBlobStorageBackend])
def test_cloud_upload_spools_large_stream_outside_memory(backend_type: type) -> None:
    # Given a seekable upload larger than the in-memory spool limit.
    source = BoundedSource(b"x" * (3 * 1024 * 1024))
    received: list[object] = []

    def receive(**kwargs: object) -> None:
        body = kwargs.get("Body", kwargs.get("data"))
        assert hasattr(body, "read")
        assert getattr(body, "_rolled") is True
        received.append(body)
        assert body.read(16) == b"x" * 16

    backend = backend_type.__new__(backend_type)
    backend._prefix = ""
    if backend_type is S3StorageBackend:
        backend._bucket = "offline-test"
        backend._client = SimpleNamespace(put_object=receive)
    else:
        backend._container_client = SimpleNamespace(
            get_blob_client=lambda _key: SimpleNamespace(upload_blob=lambda data, **_kwargs: receive(data=data)),
        )
        backend._content_settings_cls = SimpleNamespace

    # When the production backend uploads the file-like source.
    result = backend.upload("asset", source, "video/mp4")

    # Then upload receives disk-backed content and owns spool cleanup.
    assert result.size_bytes == 3 * 1024 * 1024
    assert len(received) == 1
    assert getattr(received[0], "closed") is True
