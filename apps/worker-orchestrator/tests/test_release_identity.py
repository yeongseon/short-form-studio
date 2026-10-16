from unittest.mock import Mock

import worker_release_identity


def test_ready_worker_publishes_its_runtime_identity(monkeypatch) -> None:
    client = Mock()
    monkeypatch.setenv("SOURCE_SHA", "b" * 40)
    monkeypatch.setenv("WORKER_IMAGE_DIGEST", "sha256:" + "c" * 64)
    monkeypatch.setattr(worker_release_identity.redis.Redis, "from_url", Mock(return_value=client))

    worker_release_identity.publish_release_identity()

    client.hset.assert_called_once_with(
        "release:worker-identity",
        mapping={"source_sha": "b" * 40, "digest": "sha256:" + "c" * 64},
    )
