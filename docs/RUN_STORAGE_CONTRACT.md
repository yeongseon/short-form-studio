# Run storage update contract

The in-memory and PostgreSQL run adapters share these boundaries:

- `update_run` accepts only columns in `UPDATABLE_RUN_COLUMNS`. Storage-owned
  columns (`id`, `version`, `project_id`, `workspace_id`) and unknown columns
  are rejected with `ValueError`. An empty patch is a workspace-scoped read that
  checks `expected_version` when provided; it never advances the version. A
  stale version returns `None`.
- `conditional_update_run` also rejects storage-owned and unknown columns. An
  empty patch reads the scoped run, accepts only an expected stage that is not
  in `rejected_statuses`, and does not advance the version. A missing or
  out-of-workspace run returns `(False, None)`.
- Nonempty accepted patches advance the version once. Callers that require a
  version change must supply an actual field update; an empty patch does not
  acquire an exclusive claim or atomically reserve a later update.

`RunService` stage transitions, dispatch CAS, and worker outcome transitions
submit nonempty patches. These contracts are exercised against both adapters,
including a disposable migrated PostgreSQL schema, in
`packages/creator-service/tests/test_run_adapter_parity.py`.

## Media upload ownership and reconciliation

Every workspace media upload has a durable `creator_media_upload_intents` row
before object I/O. Its `owner_id` identifies one attempt; `workspace_id` and the
workspace-prefixed `storage_key` bind that attempt to exactly one object. The
upload-intent lifecycle is also the authoritative byte and asset-slot
reservation ledger used by workspace admission and reconciliation.

States and terminal policy:

- `pending` owns a key before upload; process death leaves it for reclamation
  only after its lease expires.
- `uploaded` means object I/O completed while metadata is not yet confirmed.
- metadata success, including a registered key found after an indeterminate
  commit acknowledgement, transitions to terminal `completed`; it is never
  deleted by reconciliation. This also preserves Timeline-referenced media
  because Timeline references resolve through persisted `MediaAsset` rows.
- validation failure occurs before intent/object creation and leaves no durable
  upload state. Cancellation before object I/O immediately compensates the
  intent and releases its byte and asset-slot reservation. Cancellation after
  upload is shielded through metadata completion. A hard process death at either
  point converges through the expired lease.
- a definite metadata rollback triggers compensation. Successful deletion ends
  in terminal `reclaimed`; a delete failure remains `cleanup_pending`.
- cleanup retries are bounded. Exhausted records end in terminal `exhausted`
  for operator action and remain durable rather than losing ownership evidence.

Sweepers claim expired rows with `FOR UPDATE SKIP LOCKED`, verify a same-workspace
`creator_media_assets.storage_key` reference before deleting, and update terminal
state idempotently. Ambiguous outcomes favor preservation: no object is deleted
until the lease expires and registration has been checked by exact key.

## Workspace media capacity

Media uploads reserve their validated byte size and one asset slot on the durable
upload intent before object I/O. Admission checks `stored + reserved + incoming`
under a workspace lock. Success converts the reservation to stored metadata;
definite failures and cancellations before object I/O release bytes and the
asset slot immediately. Ambiguous process death retains capacity through a
bounded late-upload verification window. Once that window observes no object,
both byte and slot capacity are released while a zero-reservation
`late_upload_watch` tombstone remains durable to detect and remove a delayed
write. Repeated sweeps release capacity exactly once.

`MEDIA_MAX_STORED_BYTES`, `MEDIA_MAX_ASSET_COUNT`, and
`MEDIA_MAX_RESERVED_BYTES` default to `0` (unlimited). The authenticated
`GET /api/creator/workspaces/{workspace_id}/assets/storage-usage` response shows
stored and in-flight usage plus configured limits. Budget rejection is HTTP 413
with error code `STORAGE_BUDGET`. Worker-generated scene images, narration audio,
and final videos publish through the same reservation transaction into
`creator_media_assets`; `creator_scene_assets` and `creator_artifacts` rows are
aliases of that canonical object and are not counted a second time. Subtitles are
excluded because they are small text artifacts rather than image/audio/video media.

`MEDIA_TEMP_DISK_LOW_WATERMARK_BYTES` defaults to `0`; when positive it blocks
MediaAsset upload staging and image/audio/video generation before provider or
FFmpeg work starts. Reads, downloads, and cleanup remain available.

## Media retention safety

MediaAsset retention is separate from artifact expiration. It defaults to
disabled (`MEDIA_RETENTION_ENABLED=false`) and dry-run
(`MEDIA_RETENTION_DRY_RUN=true`); all original, generated-intermediate, and final
video windows default to `0`, so no arbitrary age policy is activated. Positive
windows are configured independently with `MEDIA_RETENTION_ORIGINAL_DAYS`,
`MEDIA_RETENTION_INTERMEDIATE_DAYS`, and `MEDIA_RETENTION_FINAL_VIDEO_DAYS`.
Generated worker outputs are classified by their canonical MediaAsset: final
videos use `MEDIA_RETENTION_FINAL_VIDEO_DAYS`, while scene images and narration
audio use `MEDIA_RETENTION_INTERMEDIATE_DAYS`. Active scene aliases protect their
canonical object; inactive aliases are removed transactionally with canonical
metadata after physical deletion. Legacy rows created before this release and not
linked to a canonical MediaAsset remain under artifact expiration rather than
being guessed into a workspace retention class.

Candidates must also pass `MEDIA_RETENTION_GRACE_DAYS` (default 7), exact
workspace-key ownership, current Timeline references, and approved-review
references. Dry-run reports candidates without deleting. In destructive mode,
object deletion happens before metadata deletion; a storage deletion failure
therefore leaves both metadata and accounted capacity intact. Deletion is
irreversible once the object backend confirms removal, so operators should review
dry-run output and backups before setting `MEDIA_RETENTION_DRY_RUN=false`.
