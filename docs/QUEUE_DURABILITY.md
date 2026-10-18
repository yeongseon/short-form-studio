# Queue Durability and Recovery

## Guarantee

The beta Compose topology stores Redis data on the `redis_data` named volume and
runs Redis AOF with `appendfsync everysec`. A normal Redis process restart or
container force-recreate that retains this volume should preserve acknowledged
state subject to Redis/AOF recovery. Up to roughly one second of writes may be
lost on host or storage failure. Deleting/replacing `redis_data`, corrupt storage,
or losing the host can create a new empty broker.

This is at-least-once infrastructure, not exactly-once execution. Worker loss can
redeliver messages. Database tracking, claim tokens, quota ownership, and artifact
ownership remain the authority that prevents a duplicate or late worker from
finalizing another attempt.

## Broker Replacement Recovery

Redis owns a durable `queue:recovery_epoch`. The beat reconciler remembers the
last observed epoch on the mounted DLQ volume. It considers broker messages lost
only when all of these signals agree:

1. the broker epoch changed;
2. all routed queues are empty;
3. at least one worker answers Celery inspect ping; and
4. the database task was created before the new epoch.

If any signal is unavailable, recovery is deferred. Queue age alone never fails
work, so a slow healthy backlog remains queued. With complete replacement
evidence, pre-epoch `pending`, `queued`, and `running` rows are fenced to
`failed` with `broker_message_lost`, their owned quota is released, and eligible
runs use the existing ownership-fenced rollback. `success` rows and post-epoch
manual retries are untouched.

Original broker arguments are not durably recorded. Recovery therefore never
guesses arguments or automatically re-executes work. The user must retry through
the normal authenticated UI/API, which creates a new owned attempt. A durable
transactional outbox could automate exact payload publication later, but is out
of scope.

## State Outcomes

| Event | pending | queued | running | success |
|---|---|---|---|---|
| Redis process restart, volume retained | unchanged | broker resumes backlog | worker/redelivery rules apply | unchanged |
| Container force-recreate, volume retained | unchanged | broker resumes backlog | worker/redelivery rules apply | unchanged |
| New empty broker, verified epoch change | safe failure + manual retry | safe failure + manual retry | safe failure + manual retry | unchanged |
| Slow backlog / inspect unavailable | unchanged; defer | unchanged; defer | existing stuck-task policy only | unchanged |

## DLQ Retention and Retrieval

Redis DLQ entries remain bounded by `DLQ_MAX_SIZE`. If Redis cannot accept a DLQ
entry, workers append the already-redacted JSON payload to
`/var/lib/short-form-studio/dlq/failures.jsonl` on the `dlq_data` volume. The
fallback rotates to one `.1` segment at `DLQ_FALLBACK_MAX_BYTES` (10 MiB default),
so it is bounded but older entries can be discarded. All scaled workers mount the
same volume.

Operators can collect both segments without exposing application source:

```bash
docker compose exec worker sh -c \
  'cat /var/lib/short-form-studio/dlq/failures.jsonl.1 /var/lib/short-form-studio/dlq/failures.jsonl 2>/dev/null'
```

`celery_app.read_dlq_fallback(limit=100)` provides the same bounded readback path
for operational tooling. Entries remain subject to the existing sanitizer and
redaction tests. Rotation/write failures are logged as
`dlq_retention_failure`; collection and deletion remain operator actions.

## Observability

- `worker.queue.length` records routed Redis queue length.
- `worker.queue.oldest_wait_seconds` records the oldest active `pending` or `queued` database wait.
- `worker.queue.recovery_failures` counts compensation failures.
- recovery summaries include `failed`, `deferred`, queue length, oldest wait, and
  recovery failure fields.
- `worker.dlq.retained_entries` and `worker.dlq.retention_failures` expose DLQ
  retention outcomes; structured logs include `dlq_source` and
  `dlq_retention_failure`.

The shipped base worker and most scaled stage workers use small solo pools. As
verified in PR #874, a running solo task cannot process remote revoke mid-task;
SIGTERM is warm shutdown. That topology fact does not change the conservative
broker-replacement policy.
