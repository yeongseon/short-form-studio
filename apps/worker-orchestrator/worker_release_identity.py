import json
import logging
import os
from typing import Final

import redis
from celery.signals import heartbeat_sent, worker_ready


HEARTBEAT_INTERVAL_SECONDS: Final = 60
IDENTITY_TTL_SECONDS: Final = HEARTBEAT_INTERVAL_SECONDS * 3


def _release_metadata() -> tuple[str | None, str | None]:
    return os.getenv("SOURCE_SHA") or None, os.getenv("WORKER_IMAGE_DIGEST") or None


def _write_release_identity() -> None:
    client = redis.Redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"),
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    client.set(
        f"release:worker-identity:{os.environ['HOSTNAME']}",
        json.dumps(
            {
                "source_sha": os.environ["SOURCE_SHA"],
                "digest": os.environ["WORKER_IMAGE_DIGEST"],
            },
            separators=(",", ":"),
        ),
        ex=IDENTITY_TTL_SECONDS,
    )


@worker_ready.connect
def publish_release_identity(**_kwargs: object) -> None:
    source_sha, image_digest = _release_metadata()
    if source_sha is None and image_digest is None:
        return
    if source_sha is None or image_digest is None:
        logging.getLogger(__name__).error("Worker release identity metadata is incomplete")
        return
    try:
        _write_release_identity()
    except (KeyError, redis.RedisError, OSError, ConnectionError):
        logging.getLogger(__name__).exception("Worker release identity publication failed")


@heartbeat_sent.connect
def refresh_release_identity(**_kwargs: object) -> None:
    if _release_metadata() == (None, None):
        return
    try:
        _write_release_identity()
    except (KeyError, redis.RedisError, OSError, ConnectionError):
        logging.getLogger(__name__).exception("Worker release identity refresh failed")
