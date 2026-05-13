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
