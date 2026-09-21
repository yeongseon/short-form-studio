# Timeout & Retry Policy

This document describes the timeout and retry configuration for all pipeline tasks.

---

## Task Timeout Matrix

| Task | Soft Limit | Hard Limit | Max Retries | Backoff | Queue |
|------|-----------|-----------|-------------|---------|-------|
| `generate_script` | 300s (5m) | 360s (6m) | 5 | 30s exponential | script |
| `generate_visual_plan` | 300s (5m) | 360s (6m) | 5 | 30s exponential | script |
| `generate_scene_image` | 600s (10m) | 660s (11m) | 5 | 30s exponential | image |
| `generate_audio` | 300s (5m) | 360s (6m) | 5 | 30s exponential | audio |
| `generate_paragraph_audio` | 300s (5m) | 360s (6m) | 3 | exponential | audio |
| `generate_subtitles` | 300s (5m) | 360s (6m) | 5 | 30s exponential | audio |
| `generate_paragraph_subtitles` | 300s (5m) | 360s (6m) | 3 | exponential | audio |
| `render_video` | 600s (10m) | 660s (11m) | 3 | exponential | render |
| `reconcile_stale_dispatches` | — | — | 0 | — | creator |

---

## How Timeouts Work

### Soft Time Limit (`soft_time_limit`)
Raises `SoftTimeLimitExceeded` inside the task. The task can catch this and
perform cleanup (save partial results, update status to FAILED).

### Hard Time Limit (`time_limit`)
Kills the worker process if the task exceeds this. Always set 60s above the
soft limit to allow cleanup time.

### Why Image/Render Get Longer Limits
- **Image generation** may involve external API calls with queuing (DALL-E, Stability)
- **Video render** runs FFmpeg which is CPU-bound and scales with video length

---

## Retry Strategy

### Exponential Backoff
Tasks use `retry_backoff=30` (or `retry_backoff=True`), meaning:
- 1st retry: ~30s delay
- 2nd retry: ~60s delay
- 3rd retry: ~120s delay
- 4th retry: ~240s delay
- 5th retry: ~480s delay

With jitter applied to prevent thundering herd.

### Retryable Exceptions
Tasks retry on:
- `ProviderTimeoutError` — upstream API timed out
- `RateLimitError` — upstream rate limit hit
- `ConnectionError` — network failure
- `SoftTimeLimitExceeded` — task took too long (caught and retried)

### Non-Retryable Exceptions
Tasks fail immediately on:
- `ValidationError` — invalid input data
- `ProviderAuthError` — bad API credentials
- `ValueError` — programming error in task logic

---

## Dead Letter Queue (DLQ)

Tasks that exhaust all retries are recorded to the DLQ:
- **Primary**: Redis list `dlq:creator` (max 10,000 entries, configurable via `DLQ_MAX_SIZE`)
- **Fallback**: File at `DLQ_FALLBACK_PATH` (default: `/tmp/dlq_fallback.jsonl`)

Sensitive data is redacted before DLQ storage. See `DLQ_MONITORING.md` for
operational procedures.

---

## Worker Configuration

### Global Settings (celery_app.py)
```python
worker_prefetch_multiplier = 1      # Only fetch 1 task at a time
task_acks_late = True               # Acknowledge AFTER execution (at-least-once)
task_reject_on_worker_lost = True   # Return to queue if worker dies
```

### Resource Limits
- `MAX_MEMORY_MB`: Worker memory limit (default: 4096 MB)
- Workers are killed if memory limit is exceeded (RLIMIT_AS)

---

## Tuning Recommendations

### Increasing Timeout for Slow Providers
If using a slow provider (e.g., large local model), override via environment:
```bash
# These are Celery-level settings, not per-task
CELERY_TASK_SOFT_TIME_LIMIT=900
CELERY_TASK_TIME_LIMIT=960
```

### Reducing Retries for Fast Failure
For development where you want immediate failure feedback:
```python
# In task decorator
@celery_app.task(max_retries=0, ...)
```

### Queue-Specific Scaling
Use `docker-compose.scaled-workers.yml` to scale specific queues:
```bash
docker compose -f docker-compose.yml -f docker-compose.scaled-workers.yml up -d --scale worker-image=3
```
