import os
import logging
import json
from typing import Final

import redis
from celery.signals import heartbeat_sent, worker_ready


HEARTBEAT_INTERVAL_SECONDS: Final = 60
IDENTITY_TTL_SECONDS: Final = HEARTBEAT_INTERVAL_SECONDS * 3


class ReleaseIdentityRegistrationError(RuntimeError):
    pass


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
    source_sha = os.getenv("SOURCE_SHA")
    image_digest = os.getenv("WORKER_IMAGE_DIGEST")
    if source_sha is None and image_digest is None:
        return
    if source_sha is None or image_digest is None:
        raise ReleaseIdentityRegistrationError("Worker release identity metadata is incomplete")
    try:
        _write_release_identity()
    except (KeyError, redis.RedisError, OSError, ConnectionError) as error:
        raise ReleaseIdentityRegistrationError("Worker release identity registration failed") from error


@heartbeat_sent.connect
def refresh_release_identity(**_kwargs: object) -> None:
    if os.getenv("SOURCE_SHA") is None and os.getenv("WORKER_IMAGE_DIGEST") is None:
        return
    try:
        _write_release_identity()
    except (KeyError, redis.RedisError, OSError, ConnectionError):
        logging.getLogger(__name__).exception("Worker release identity refresh failed")
