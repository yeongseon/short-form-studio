from unittest.mock import ANY, Mock

import worker_release_identity


def test_ready_worker_publishes_its_runtime_identity(monkeypatch) -> None:
    client = Mock()
    monkeypatch.setenv("SOURCE_SHA", "b" * 40)
    monkeypatch.setenv("WORKER_IMAGE_DIGEST", "sha256:" + "c" * 64)
    monkeypatch.setenv("HOSTNAME", "worker-1")
    from_url = Mock(return_value=client)
    monkeypatch.setattr(worker_release_identity.redis.Redis, "from_url", from_url)

    worker_release_identity.publish_release_identity()

    client.set.assert_called_once_with(
        ANY,
        '{"source_sha":"' + "b" * 40 + '","digest":"sha256:' + "c" * 64 + '"}',
        ex=120,
    )
    assert client.set.call_args.args[0].startswith("release:worker-identity:")
    from_url.assert_called_once_with(
        "redis://redis:6379/0",
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def test_ready_worker_keeps_starting_when_identity_store_is_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_SHA", "b" * 40)
    monkeypatch.setenv("WORKER_IMAGE_DIGEST", "sha256:" + "c" * 64)
    monkeypatch.setattr(
        worker_release_identity.redis.Redis,
        "from_url",
        Mock(side_effect=ConnectionError("unavailable")),
    )

    worker_release_identity.publish_release_identity()


def test_ready_worker_skips_identity_publication_without_release_metadata(monkeypatch) -> None:
    # Given a local worker that was not launched from an approved release image.
    monkeypatch.delenv("SOURCE_SHA", raising=False)
    monkeypatch.delenv("WORKER_IMAGE_DIGEST", raising=False)
    from_url = Mock()
    monkeypatch.setattr(worker_release_identity.redis.Redis, "from_url", from_url)

    # When the worker-ready signal fires.
    worker_release_identity.publish_release_identity()

    # Then startup continues without contacting Redis or reporting an identity.
    from_url.assert_not_called()
