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
