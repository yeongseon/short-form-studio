# DLQ Monitoring and Alerting Guide

## Overview

The Dead Letter Queue (DLQ) is a critical operational mechanism for the Celery worker. Failed tasks that cannot be retried automatically are placed in the DLQ for manual intervention. This guide covers monitoring, alerting, and recovery procedures.

## Configuration

The `celery_app.py` is configured with the following DLQ-critical settings:

```python
celery_app.conf.update(
    task_acks_late=True,                              # Ack only after successful execution
    task_reject_on_worker_lost=True,                  # Reject tasks if worker dies
    worker_cancel_long_running_tasks_on_connection_loss=True,  # Cancel tasks on disconnect
)
```

### Configuration Details

- **`task_acks_late=True`**: Messages are acknowledged AFTER task execution. If a worker crashes mid-task, the message is redelivered to another worker.
- **`task_reject_on_worker_lost=True`**: If a worker connection is lost, tasks are rejected and returned to the broker queue.
- **Worker prefetch**: Set to 1 (`worker_prefetch_multiplier=1`) to prevent workers from claiming more tasks than they can process.

These settings ensure **at-least-once delivery semantics** and facilitate DLQ placement for unhandled failures.

## Monitoring Strategies

### 1. Redis CLI (Direct Queue Inspection)

Check DLQ size using Redis CLI:

```bash
# Connect to Redis
redis-cli -u redis://redis:6379/0

# Check DLQ size
LLEN celery:unacked_index
LLEN celery:celery_tasks:dlq  # Task list length (if DLQ key exists)

# List first N tasks in DLQ
LRANGE celery:dlq 0 9

# Inspect a specific task
HGETALL celery:task:{task_id}
```

### 2. Flower (Celery Monitoring UI)

Flower provides a web UI for task monitoring. Access at `http://localhost:5555` (if running via docker-compose).

**Checking DLQ via Flower:**
1. Navigate to **Tasks** tab
2. Filter by task state: **FAILURE**
3. Look for tasks with `Max retries exceeded` or similar error messages
4. Click a task to view full error traceback and arguments

**Limitations:** Flower does not directly expose DLQ inspection in the UI. Use Redis CLI or custom scripts for detailed DLQ introspection.

### 3. Custom Python Monitoring Script

Use this script to inspect and monitor the DLQ programmatically:

```python
#!/usr/bin/env python3
"""Monitor and inspect the Celery DLQ."""

import json
import os
import redis
from datetime import datetime, timezone

def check_dlq_size():
    """Return current DLQ size."""
    r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    
    # DLQ is stored as a list under 'celery:unacked_index'
    dlq_size = r.llen("celery:unacked_index")
    print(f"DLQ Size (unacked): {dlq_size}")
    
    return dlq_size

def list_dlq_tasks(limit=20):
    """List tasks in DLQ."""
    r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    
    # Fetch task IDs from unacked index
    task_ids = r.lrange("celery:unacked_index", 0, limit - 1)
    
    for task_id in task_ids:
        task_id_str = task_id.decode('utf-8') if isinstance(task_id, bytes) else task_id
        # Fetch task details
        task_data = r.hgetall(f"celery:task:{task_id_str}")
        if task_data:
            print(f"\nTask ID: {task_id_str}")
            for key, val in task_data.items():
                print(f"  {key.decode() if isinstance(key, bytes) else key}: {val.decode() if isinstance(val, bytes) else val}")

def check_dlq_age():
    """Check age of oldest DLQ task."""
    r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    
    # Get the oldest task ID (LINDEX -1)
    oldest_task_id = r.lindex("celery:unacked_index", -1)
    if not oldest_task_id:
        print("DLQ is empty.")
        return None
    
    oldest_task_id_str = oldest_task_id.decode('utf-8') if isinstance(oldest_task_id, bytes) else oldest_task_id
    task_data = r.hgetall(f"celery:task:{oldest_task_id_str}")
    
    # Task timestamps are in ISO format
    if b'sent' in task_data:
        sent_time_str = task_data[b'sent'].decode('utf-8')
        try:
            sent_time = datetime.fromisoformat(sent_time_str.replace('Z', '+00:00'))
            age = datetime.now(timezone.utc) - sent_time
            print(f"Oldest task age: {age.total_seconds():.0f} seconds ({age.days}d {age.seconds // 3600}h)")
            return age
        except Exception as e:
            print(f"Could not parse timestamp: {e}")
    
    return None

if __name__ == "__main__":
    print("=== Celery DLQ Monitor ===")
    dlq_size = check_dlq_size()
    
    if dlq_size > 0:
        print("\n--- DLQ Tasks ---")
        list_dlq_tasks(limit=10)
        print("\n--- DLQ Age ---")
        check_dlq_age()
    else:
        print("DLQ is healthy (empty).")
```

Run with:
```bash
cd apps/worker-orchestrator
python3 -c "exec(open('dlq_monitor.py').read())"
```

## Alerting Setup

### Recommended Alerting Thresholds

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| DLQ Size | > 5 tasks | > 20 tasks | Page on-call; check recent worker logs |
| DLQ Age | > 1 hour | > 24 hours | Immediate investigation; risk of data loss |
| Worker Count | 0 workers | N/A | Critical; no tasks can be processed |
| Task Retry Rate | > 10% of tasks | > 50% of tasks | Review error patterns; check provider health |

### Prometheus Integration

Add this to your Prometheus scrape config to monitor DLQ via a custom exporter:

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'celery_dlq'
    static_configs:
      - targets: ['localhost:8000']  # Custom DLQ exporter endpoint
    metrics_path: '/metrics/dlq'
```

**Custom DLQ Exporter (FastAPI):**

```python
# apps/api/src/shorts_api/routes/monitoring.py
from fastapi import APIRouter, Response
from creator_service.celery_monitoring import get_dlq_size, get_dlq_age
import redis
import os

router = APIRouter(prefix="/metrics", tags=["monitoring"])

@router.get("/dlq")
async def dlq_metrics() -> Response:
    """Prometheus-format DLQ metrics."""
    r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    dlq_size = r.llen("celery:unacked_index")
    
    metrics = f"""# HELP celery_dlq_size Number of tasks in Dead Letter Queue
# TYPE celery_dlq_size gauge
celery_dlq_size {dlq_size}
"""
    return Response(content=metrics, media_type="text/plain")
```

### PagerDuty Integration

Configure an HTTP webhook to trigger PagerDuty alerts when DLQ size exceeds threshold:

```python
# apps/worker-orchestrator/dlq_alerter.py
import os
import redis
import requests
from datetime import datetime

def check_and_alert(dlq_threshold=20):
    """Check DLQ and send PagerDuty alert if threshold exceeded."""
    r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    dlq_size = r.llen("celery:unacked_index")
    
    if dlq_size > dlq_threshold:
        webhook_url = os.getenv("PAGERDUTY_WEBHOOK_URL")
        if not webhook_url:
            return
        
        payload = {
            "routing_key": os.getenv("PAGERDUTY_ROUTING_KEY"),
            "event_action": "trigger",
            "dedup_key": f"celery_dlq_alert_{datetime.now().date()}",
            "payload": {
                "summary": f"Celery DLQ alert: {dlq_size} tasks in queue",
                "severity": "critical" if dlq_size > 50 else "warning",
                "source": "celery-worker",
                "custom_details": {
                    "dlq_size": dlq_size,
                    "threshold": dlq_threshold,
                }
            }
        }
        
        requests.post(webhook_url, json=payload)
```

### Datadog Integration

Use Datadog's Celery integration to automatically track DLQ metrics:

```yaml
# datadog-agent config
init_config:

instances:
  - celery_broker_url: redis://redis:6379/0
    celery_default_queue: creator

# In Datadog dashboard, create monitor:
# celery.queue.size > 20 for 5m
```

## Task Failure Recovery

### Replaying Failed Tasks from DLQ

Once a task is identified and fixed, replay it:

```python
#!/usr/bin/env python3
"""Replay a task from the DLQ."""

import sys
import json
from celery_app import celery_app
import redis
import os

def replay_task(task_id: str):
    """Replay a task by its ID."""
    r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    
    # Get task data
    task_data = r.hgetall(f"celery:task:{task_id}")
    if not task_data:
        print(f"Task {task_id} not found in DLQ.")
        return False
    
    # Parse task arguments and function name
    task_name = task_data.get(b'name', b'').decode('utf-8')
    args = json.loads(task_data.get(b'args', b'[]'))
    kwargs = json.loads(task_data.get(b'kwargs', b'{}'))
    
    print(f"Replaying task: {task_name}")
    print(f"  Args: {args}")
    print(f"  Kwargs: {kwargs}")
    
    # Resend task
    task_func = celery_app.tasks.get(task_name)
    if task_func is None:
        print(f"Task function {task_name} not found.")
        return False
    
    # Invoke with original args
    task_func.apply_async(args=args, kwargs=kwargs)
    
    # Remove from DLQ after successful replay
    r.lrem("celery:unacked_index", 0, task_id.encode())
    r.delete(f"celery:task:{task_id}")
    
    print(f"Task {task_id} replayed and removed from DLQ.")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python replay_task.py <task_id>")
        sys.exit(1)
    
    task_id = sys.argv[1]
    replay_task(task_id)
```

### Bulk Clearing DLQ (Use with Caution)

```bash
# Clear ALL DLQ tasks (CAREFUL!)
redis-cli -u redis://redis:6379/0
DEL celery:unacked_index
# Clear all task metadata
EVAL "return redis.call('del', unpack(redis.call('keys', ARGV[1])))" 0 "celery:task:*"
```

## Operational Runbook

### Alert: DLQ Size > 20

1. **Immediate Actions:**
   - Check recent worker logs: `docker logs short-form-studio-worker-1`
   - Verify workers are running: `celery -A celery_app inspect active`
   - Check Redis connectivity: `redis-cli ping`

2. **Root Cause Analysis:**
   - Check error messages in task metadata
   - Identify common failure patterns (provider timeouts, rate limits, etc.)
   - Review recent code changes or provider updates

3. **Recovery:**
   - Fix underlying issue (e.g., provider credentials, rate limit handling)
   - Replay critical tasks using the replay script
   - Monitor DLQ size decline

4. **Prevention:**
   - Increase retry parameters if failures are transient
   - Add provider health checks before task execution
   - Implement circuit breaker pattern for failing providers

### Alert: Worker Count = 0

1. **Immediate Actions:**
   - Restart worker: `docker restart short-form-studio-worker-1`
   - Check Docker logs for startup errors
   - Verify database connectivity

2. **Escalation:**
   - If restart fails, check network/infrastructure health
   - Review recent dependency changes

### Alert: DLQ Age > 24 Hours

1. **Risk:** Task is likely stale; manual investigation required
2. **Actions:**
   - Inspect task details and associated run ID
   - Check if run is still valid (not already completed/failed elsewhere)
   - Decide: replay, discard, or investigate offline

## Best Practices

1. **Monitor proactively:** Check DLQ daily in non-prod, continuously in prod
2. **Act quickly:** DLQ tasks are typically urgent; treat high sizes as critical
3. **Log comprehensively:** Each task failure includes full context in metadata
4. **Automate recovery:** Script replay workflows for common failure patterns
5. **Test alerting:** Regularly simulate DLQ conditions to validate alerting
6. **Document runbooks:** Keep this guide updated with team-specific procedures

## Related Documentation

- Celery: https://docs.celeryproject.org/
- Flower: https://flower.readthedocs.io/
- Redis: https://redis.io/docs/
