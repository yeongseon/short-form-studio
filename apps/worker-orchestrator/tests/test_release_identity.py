import logging
from unittest.mock import ANY, Mock

import pytest
from celery.signals import worker_ready

import worker_release_identity


def set_env(monkeypatch, name: str, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)


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
        ex=worker_release_identity.IDENTITY_TTL_SECONDS,
    )
    assert client.set.call_args.args[0].startswith("release:worker-identity:")
    from_url.assert_called_once_with(
        "redis://redis:6379/0",
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def test_ready_worker_logs_identity_publication_failure_when_store_is_unavailable(
    monkeypatch, caplog
) -> None:
    # Given release metadata and an unavailable identity store.
    monkeypatch.setenv("SOURCE_SHA", "b" * 40)
    monkeypatch.setenv("WORKER_IMAGE_DIGEST", "sha256:" + "c" * 64)
    monkeypatch.setattr(
        worker_release_identity.redis.Redis,
        "from_url",
        Mock(side_effect=ConnectionError("unavailable")),
    )

    # When Celery dispatches the real worker-ready signal.
    with caplog.at_level(logging.ERROR, logger=worker_release_identity.__name__):
        responses = worker_ready.send(sender=Mock())

    # Then publication failure is observable without pretending the signal aborts startup.
    response = next(
        result
        for receiver, result in responses
        if receiver is worker_release_identity.publish_release_identity
    )
    assert response is None
    assert "Worker release identity publication failed" in caplog.messages


def test_worker_heartbeat_refreshes_its_runtime_identity(monkeypatch) -> None:
    client = Mock()
    monkeypatch.setenv("SOURCE_SHA", "b" * 40)
    monkeypatch.setenv("WORKER_IMAGE_DIGEST", "sha256:" + "c" * 64)
    monkeypatch.setenv("HOSTNAME", "worker-1")
    monkeypatch.setattr(worker_release_identity.redis.Redis, "from_url", Mock(return_value=client))

    worker_release_identity.refresh_release_identity()

    client.set.assert_called_once_with(ANY, ANY, ex=worker_release_identity.IDENTITY_TTL_SECONDS)
    assert worker_release_identity.IDENTITY_TTL_SECONDS > worker_release_identity.HEARTBEAT_INTERVAL_SECONDS


def test_ready_worker_logs_partial_release_metadata(monkeypatch, caplog) -> None:
    # Given only half of the required release metadata.
    monkeypatch.setenv("SOURCE_SHA", "b" * 40)
    monkeypatch.delenv("WORKER_IMAGE_DIGEST", raising=False)

    # When Celery dispatches the real worker-ready signal.
    with caplog.at_level(logging.ERROR, logger=worker_release_identity.__name__):
        responses = worker_ready.send(sender=Mock())

    # Then Celery reports the receiver failure instead of aborting worker startup.
    response = next(
        result
        for receiver, result in responses
        if receiver is worker_release_identity.publish_release_identity
    )
    assert response is None
    assert "Worker release identity metadata is incomplete" in caplog.messages


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


@pytest.mark.parametrize("source_sha", [None, ""])
@pytest.mark.parametrize("image_digest", [None, ""])
def test_ready_worker_treats_empty_release_metadata_as_absent(
    monkeypatch, caplog, source_sha: str | None, image_digest: str | None
) -> None:
    # Given an image built without release build args, whose Dockerfile exports empty strings.
    set_env(monkeypatch, "SOURCE_SHA", source_sha)
    set_env(monkeypatch, "WORKER_IMAGE_DIGEST", image_digest)
    from_url = Mock()
    monkeypatch.setattr(worker_release_identity.redis.Redis, "from_url", from_url)

    # When the worker-ready signal fires.
    with caplog.at_level(logging.ERROR, logger=worker_release_identity.__name__):
        worker_release_identity.publish_release_identity()

    # Then it behaves like a local worker: no Redis contact and nothing logged as an error.
    from_url.assert_not_called()
    assert caplog.messages == []


@pytest.mark.parametrize("source_sha", [None, ""])
@pytest.mark.parametrize("image_digest", [None, ""])
def test_worker_heartbeat_skips_identity_refresh_without_release_metadata(
    monkeypatch, caplog, source_sha: str | None, image_digest: str | None
) -> None:
    # Given a worker without release metadata, unset or exported as empty strings.
    set_env(monkeypatch, "SOURCE_SHA", source_sha)
    set_env(monkeypatch, "WORKER_IMAGE_DIGEST", image_digest)
    from_url = Mock()
    monkeypatch.setattr(worker_release_identity.redis.Redis, "from_url", from_url)

    # When Celery sends a heartbeat.
    with caplog.at_level(logging.ERROR, logger=worker_release_identity.__name__):
        worker_release_identity.refresh_release_identity()

    # Then no identity refresh is attempted and no error is logged per heartbeat.
    from_url.assert_not_called()
    assert caplog.messages == []
