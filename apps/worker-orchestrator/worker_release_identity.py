import os
import logging
import json

import redis
from celery.signals import worker_ready


@worker_ready.connect
def publish_release_identity(**_kwargs: object) -> None:
    source_sha = os.getenv("SOURCE_SHA")
    image_digest = os.getenv("WORKER_IMAGE_DIGEST")
    if source_sha is None and image_digest is None:
        return
    try:
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
            ex=120,
        )
    except (KeyError, redis.RedisError, OSError):
        logging.getLogger(__name__).exception("Worker release identity publication failed")
