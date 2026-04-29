# DLQ Monitoring and Alerting Guide

## Overview

This worker uses Redis as the Celery broker, so AMQP dead-letter exchanges are not used.
Instead, terminal task failures are captured by a Celery `task_failure` signal handler and
stored as JSON entries in Redis list `dlq:creator`.

Each DLQ entry includes:

- `task_id`
- `task_name`
- `args`
- `kwargs`
- `exception`
- `timestamp`

## Implementation Source

See `apps/worker-orchestrator/celery_app.py`:

- Queue config contains only the Redis-backed `creator` queue (no AMQP dead-letter arguments).
- `handle_task_failure` writes failed task payloads to `dlq:creator` with `LPUSH` + `LTRIM`.
- If Redis write fails at failure time, the same JSON payload is appended to a local fallback file (`DLQ_FALLBACK_PATH`, default `/tmp/dlq_fallback.jsonl`).

## Monitoring with Redis CLI

```bash
# Connect
redis-cli -u redis://redis:6379/0

# DLQ size
LLEN dlq:creator

# Newest 10 DLQ entries
LRANGE dlq:creator -10 -1
```

Each list entry is a JSON object for one failed task.

## Python Monitoring Snippet

```python
import json
import os
import redis

r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))

size = r.llen("dlq:creator")
print(f"DLQ size: {size}")

for raw in r.lrange("dlq:creator", -10, -1):
    entry = json.loads(raw)
    print(entry["timestamp"], entry["task_name"], entry["task_id"])
```

## Alerting Recommendations

- Warning: `LLEN dlq:creator > 5` for 5 minutes
- Critical: `LLEN dlq:creator > 20` for 5 minutes

## Recovery Workflow

1. Inspect recent DLQ entries from `dlq:creator`.
2. Group by `task_name` and `exception` to identify common failure cause.
3. Fix the root cause.
4. Requeue tasks from stored `task_name`/`args`/`kwargs` using Celery once safe.

## Important Notes

- DLQ capture is best-effort by design. If Redis is unavailable during task failure, the Redis DLQ entry can be lost; the failure is still recorded in application logs, and the fallback file captures the payload when local disk write succeeds.
- Monitor fallback-file growth (`DLQ_FALLBACK_PATH`) as a signal of Redis instability during failure handling.
- `celery:unacked_index` is an in-flight/unacked transport structure, not a DLQ.
- Do not treat `celery:unacked_index` as failed-task storage for alerting or replay.
