import os
import logging

import redis
from celery.signals import worker_ready


@worker_ready.connect
def publish_release_identity(**_kwargs: object) -> None:
    try:
        client = redis.Redis.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379/0"),
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        client.hset(
            "release:worker-identity",
            mapping={
                "source_sha": os.environ["SOURCE_SHA"],
                "digest": os.environ["WORKER_IMAGE_DIGEST"],
            },
        )
    except (KeyError, redis.RedisError, OSError):
        logging.getLogger(__name__).exception("Worker release identity publication failed")
