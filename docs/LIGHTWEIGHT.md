# Lightweight Mode

Lightweight mode lets you run the API pipeline without Celery and Redis.
When `REDIS_URL` is not set, task dispatch runs worker task functions synchronously in-process.

## When To Use

- Local development where you only run the API service.
- Debugging task behavior without queue infrastructure.
- Small single-user environments where async queueing is not required.

## How It Works

- `REDIS_URL` set: API dispatches tasks with Celery `apply_async(...)` (existing behavior).
- `REDIS_URL` unset or empty: API calls the same worker task entrypoints directly.
- Synchronous failures are caught; run status is moved to `FAILED` to avoid silent stuck stages.

## Enable Lightweight Mode

1. Unset `REDIS_URL` in your environment.
2. Start API normally.
3. Trigger pipeline stages from the UI or API.

Example:

```bash
unset REDIS_URL
cd apps/api
uvicorn shorts_api.main:app --reload
```

## Notes

## Production Warning

Lightweight mode is **not suitable for production use**. It runs tasks synchronously
in the API process, which blocks request handling and provides no task isolation,
retry logic, or horizontal scaling. Always use Celery + Redis in production.

- Tasks execute during the request lifecycle, so requests can take longer.
- Celery task IDs are replaced with synthetic `sync-...` IDs in lightweight mode.
- No worker process is required for dispatch execution in this mode.

## API Response Semantics

In normal (Celery) mode, generation trigger endpoints return `202 Accepted` because
the task is enqueued and runs asynchronously. In lightweight mode, the **same endpoints**
still return `202` but the task has already completed (or failed) by the time the
response is sent. The response body contains the updated run state.

This means:
- Requests may take significantly longer (seconds to minutes) depending on the AI provider.
- The client receives the final result immediately rather than needing to poll.
- Timeouts at the HTTP/proxy layer may need adjustment for long-running tasks.
# Async request boundaries

Generation requests still await lightweight task completion and return the same
task identity or error. Blocking execution runs in a bounded AnyIO worker thread;
health and cancellation requests can continue on the API event loop. Each
lightweight invocation owns a temporary worker loop and DB pool, closed before
the invocation returns. Celery workers retain their persistent process loop.

API offload limits per event loop are eight dispatch operations, four control
operations (independent so saturated generation cannot starve revocation), and
one serialized admin rate-limit operation. Media services allow four simultaneous
validation/probe/storage operations per service instance.

Thread cancellation does not stop Python threads. These boundaries use AnyIO's
non-abandoning wait. Dispatch ownership is shielded through reservation,
publication, tracking, and post-dispatch cancellation compensation. An accepted
media upload is shielded through its asset-row save. A disconnected client does
not make an in-progress publish safe to retry; use the existing run/task state.
Shutdown must allow these owned operations to finish; downstream timeouts still
govern their duration. Cancellation before entering an owned operation can stop it.

This does not change upload buffering: video/audio/image routes still accept
whole byte payloads up to their existing limits (#814). Cloud-storage outage
latency and production throughput are not measured by the local boundary tests.
