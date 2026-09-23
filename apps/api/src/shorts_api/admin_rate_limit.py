import hashlib
import logging
import os
import time
from collections import defaultdict

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class DestructiveOpRateLimiter:
    def __init__(self, max_ops_per_minute: int = 10):
        self.max_ops_per_minute = max_ops_per_minute
        self.operations: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, endpoint_or_admin_key: str, admin_key: str | None = None) -> bool:
        key = admin_key if admin_key is not None else endpoint_or_admin_key
        now = time.time()
        if key in self.operations:
            self.operations[key] = [ts for ts in self.operations[key] if ts > now - 60]
        if len(self.operations[key]) < self.max_ops_per_minute:
            self.operations[key].append(now)
            return True
        return False

    def get_remaining_ops(self, admin_key: str) -> int:
        one_minute_ago = time.time() - 60
        if admin_key in self.operations:
            recent = [ts for ts in self.operations[admin_key] if ts > one_minute_ago]
            return max(0, self.max_ops_per_minute - len(recent))
        return self.max_ops_per_minute


class RedisRateLimiter:
    def __init__(self, max_ops: int = 10, window_seconds: int = 60, redis_url: str | None = None):
        self.max_ops = max_ops
        self.window_seconds = window_seconds
        self._fallback = DestructiveOpRateLimiter(max_ops_per_minute=max_ops)
        self._redis: Redis | None = None
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self._redis_retry_after: float = 0.0

    @staticmethod
    def _key_hash(admin_key: str) -> str:
        return hashlib.sha256(admin_key.encode("utf-8")).hexdigest()

    def _redis_key(self, endpoint: str, admin_key: str) -> str:
        endpoint_key = endpoint.strip("/").replace("/", ":") or "root"
        return f"ratelimit:{endpoint_key}:{self._key_hash(admin_key)}"

    def is_allowed(self, endpoint: str, admin_key: str) -> bool:
        if self._redis is None and time.time() >= self._redis_retry_after:
            try:
                client = Redis.from_url(self._redis_url, decode_responses=True)
                client.ping()
                self._redis = client
                logger.info("Redis rate limiter reconnected successfully")
            except Exception:
                self._redis_retry_after = time.time() + 60
        if self._redis is None:
            return self._fallback.is_allowed(admin_key)
        try:
            key = self._redis_key(endpoint, admin_key)
            with self._redis.pipeline() as pipe:
                pipe.incr(key)
                pipe.expire(key, self.window_seconds)
                count, _ = pipe.execute()
            return int(count) <= self.max_ops
        except RedisError as exc:
            logger.warning(
                "Redis rate limit operation failed; falling back to in-memory limiter (will retry in 60s): %s", exc,
            )
            self._redis = None
            self._redis_retry_after = time.time() + 60
            return self._fallback.is_allowed(admin_key)
