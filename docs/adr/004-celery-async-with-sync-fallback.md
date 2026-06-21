# ADR-004: Celery Async Dispatch with Synchronous Fallback

**Status**: Accepted  
**Date**: 2026-05-12  
**Decision makers**: @yeongseon

## Context

AI pipeline tasks (script generation, image generation, TTS, rendering) are long-running operations (seconds to minutes). The API must remain responsive while these run. Two execution models were evaluated:

1. **In-process (synchronous)**: Run tasks in the API process on background threads.
2. **Out-of-process (Celery + Redis)**: Queue tasks to dedicated worker processes via Redis broker.

## Decision

**Use Celery for production dispatch with an automatic synchronous fallback when `REDIS_URL` is unset.**

### Celery dispatch (default — production)

```python
# task_dispatch_service.py
def _use_celery_dispatch(self) -> bool:
    return bool(os.environ.get("REDIS_URL"))

# When Celery is available:
result = task.apply_async(args=args, kwargs=kwargs, headers=trace_headers)
```

- Tasks execute in isolated `apps/worker-orchestrator` processes
- Per-queue routing: `scripts`, `images`, `audio`, `render`, `default`
- `task_acks_late=True` — messages survive worker crashes
- `task_reject_on_worker_lost=True` — no message loss on disconnect
- Dead letter queue (`dlq:creator`) for terminal failures
- Worker autoscaling per queue via `docker-compose.scaled-workers.yml`

### Synchronous fallback (development — no Redis)

```python
# When REDIS_URL is unset:
sync_self = SimpleNamespace(request=SimpleNamespace(id=task_id, retries=0))
with ThreadPoolExecutor(max_workers=1) as executor:
    future = executor.submit(task.run, sync_self, *args, **kwargs)
    future.result()
```

- Runs the task function directly in a thread pool
- Provides a fake `self.request` context matching Celery's interface
- Marks run as FAILED on any exception
- Enables local development without Redis/Celery infrastructure

### Why Celery over alternatives

| Alternative | Rejected because |
|---|---|
| asyncio background tasks | No persistence — lost on process restart |
| Dramatiq | Smaller ecosystem, less battle-tested at scale |
| Temporal/Airflow | Overkill for linear pipeline (see ADR-002) |
| RQ (Redis Queue) | Lacks per-queue routing, DLQ, and autoscaling |

## Consequences

- Production requires Redis + at least one Celery worker
- Development works with zero infrastructure (just `REDIS_URL` unset)
- Task functions must be importable by both worker and API (shared `tasks/` module)
- All dispatch goes through `TaskDispatchService` — the single dispatch abstraction
- OpenTelemetry trace headers propagate through Celery task headers for distributed tracing
