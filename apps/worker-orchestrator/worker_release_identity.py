import os

import redis
from celery.signals import worker_ready


@worker_ready.connect
def publish_release_identity(**_kwargs: object) -> None:
    client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    client.hset(
        "release:worker-identity",
        mapping={
            "source_sha": os.environ["SOURCE_SHA"],
            "digest": os.environ["WORKER_IMAGE_DIGEST"],
        },
    )
