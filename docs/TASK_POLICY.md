# Task Timeout & Retry Policy

This document describes the timeout and retry configuration for each pipeline
stage task in the worker orchestrator.

---

## Overview

All tasks use Celery's built-in retry mechanism with:
- **Exponential backoff** with jitter to avoid thundering herd
- **Auto-retry** on `ProviderTimeoutError` and `RateLimitError`
- **Soft time limit** (raises `SoftTimeLimitExceeded` — task can clean up)
- **Hard time limit** (kills task unconditionally — 60s after soft limit)

---

## Per-Stage Configuration

| Task | Queue | Soft Limit | Hard Limit | Max Retries | Backoff | Notes |
|------|-------|-----------|-----------|-------------|---------|-------|
| `generate_script` | script | 300s (5m) | 360s (6m) | 5 | 30s × 2^n | LLM call |
| `generate_visual_plan` | script | 300s (5m) | 360s (6m) | 5 | 30s × 2^n | LLM call |
| `generate_scene_image` | image | 600s (10m) | 660s (11m) | 5 | 30s × 2^n | GPU/API image gen |
| `generate_audio` | audio | 300s (5m) | 360s (6m) | 5 | 30s × 2^n | TTS provider |
| `generate_paragraph_audio` | audio | 300s (5m) | 360s (6m) | 3 | exp backoff | Per-paragraph TTS |
| `generate_subtitles` | audio | 300s (5m) | 360s (6m) | 5 | 30s × 2^n | STT provider |
| `generate_paragraph_subtitles` | audio | 300s (5m) | 360s (6m) | 3 | exp backoff | Per-paragraph STT |
| `render_video` | render | 600s (10m) | 660s (11m) | 3 | exp backoff | FFmpeg rendering |
| `reconcile_stale_dispatches` | creator | — | — | 0 | — | Beat task (60s interval) |

---

## Retry Behavior

### Retryable Errors (auto-retry)

| Exception | Behavior |
|-----------|----------|
| `ProviderTimeoutError` | Auto-retry with backoff |
| `RateLimitError` | Auto-retry with backoff |

### Non-Retryable Errors (immediate failure)

| Exception | Behavior |
|-----------|----------|
| `ProviderError` (base) | Task fails, run marked as failed |
| `ValidationError` | Task fails (bad input, no point retrying) |
| `SoftTimeLimitExceeded` | Re-raised as `ProviderTimeoutError` for retry |
| Other unhandled | Task fails, stored in DLQ |

### Backoff Calculation

```
delay = min(retry_backoff × 2^(retry_count), max_backoff)
       + random_jitter(0, delay × 0.5)
```

Default `retry_backoff=30` means:
- 1st retry: ~30-45s
- 2nd retry: ~60-90s
- 3rd retry: ~120-180s
- 4th retry: ~240-360s
- 5th retry: ~480-720s

---

## Queue Configuration

Workers can subscribe to specific queues for independent scaling:

```bash
# All queues (default single-worker setup)
celery -A celery_app worker -Q creator,script,image,audio,render

# Scale image generation independently (GPU worker)
celery -A celery_app worker -Q image --concurrency=2

# Dedicated LLM worker
celery -A celery_app worker -Q script --concurrency=4

# Render worker (CPU-bound, single concurrency recommended)
celery -A celery_app worker -Q render --concurrency=1
```

---

## Failure Handling

### Dead Letter Queue (DLQ)

Tasks that exhaust all retries are stored in Redis list `dlq:creator` with:
- Task name, args, kwargs
- Exception type and traceback
- Timestamp
- Worker hostname

DLQ max size is controlled by `DLQ_MAX_SIZE` env var (default: 10000).
If Redis is unavailable, failures are written to `DLQ_FALLBACK_PATH` (JSONL file).

### Run Status on Failure

When a task permanently fails:
1. Task tracking record updated: `status = "failed"`
2. Pipeline run: `status = "failed"`, `error_message` set
3. No stage transition occurs — run stays at the generating stage

### Stale Task Reconciliation

The `reconcile_stale_dispatches` beat task runs every 60 seconds and:
1. Finds tasks stuck in `pending` state for > threshold
2. Marks them as failed (cannot re-enqueue without persisted args)
3. Updates the associated run status

---

## Tuning Guidelines

### When to Increase Timeouts

- Image generation with high-resolution models: increase `generate_scene_image` soft_time_limit
- Slow LLM providers (e.g., local Ollama on CPU): increase script/visual_plan limits
- Long videos (> 60s): increase `render_video` limits

### When to Increase Retries

- Unreliable network to external providers: increase max_retries
- Rate-limited APIs with strict quotas: increase max_retries + backoff

### When to Decrease Retries

- Local providers (Ollama, local SD): reduce to 2-3 (failures are likely persistent)
- Development/testing: set `max_retries=0` to fail fast

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DLQ_MAX_SIZE` | 10000 | Maximum entries in Redis DLQ |
| `DLQ_FALLBACK_PATH` | `/tmp/dlq_fallback.jsonl` | File path when Redis DLQ unavailable |
| `CELERY_TASK_ROUTES` | — | JSON override for task routing |
