# Storyboard pending-first dispatch follow-up

## Implementation

- Single and bulk storyboard dispatch share `_publish_pending`: generate UUID,
  await `record_task_pending`, publish using that UUID, then CAS-promote pending
  to queued. A pending write failure prevents publishing.
- All four paragraph endpoints pass the ID through the existing audio/subtitle
  wrappers. Bulk entries each receive a distinct UUID.
- Publish errors (including lost broker acknowledgement) and promotion errors
  revoke the known ID through the configured dispatcher, mark tracking revoked,
  and release quota. Revoke failure does not prevent tracking/quota compensation.
- Preflight/postflight cancellation checks and single/bulk error response shapes
  remain intact. Atomic promotion preserves running/terminal/cancelled task state;
  rollback retains storage's protection for successful tasks.
- Lightweight execution honors a supplied task ID; otherwise its existing
  synthetic-ID behavior remains intact.

## TDD evidence

All commands ran in `/tmp/opencode/short-form-refactor`, using
`/data/GitHub/short-form-studio/.venv/bin/python` and absolute worktree PYTHONPATH
entries for the three packages, `apps/api/src`, and `apps/worker-orchestrator`.

- Baseline: `-m pytest apps/api/tests/test_creator_storyboard.py apps/api/tests/test_storyboard_cancelled.py apps/api/tests/test_task_dispatch_adapter.py -q`
  → **37 passed** before production edits.
- Red: `-m pytest apps/api/tests/test_storyboard_pending_dispatch.py -q`
  → **20 failed, 4 passed** before implementation: old dispatch never passed a
  preregistered ID and had no pending/promotion sequence. Pending-attempt assertions
  were subsequently added so a failure before entering publication cannot masquerade
  as successful pending-write failure handling.
- Red: `-m pytest apps/api/tests/test_task_dispatch_adapter.py::test_lightweight_runner_uses_preregistered_id -q`
  → **1 failed**: the adapter replaced the supplied pending ID with a synthetic ID.
- Green focused run: storyboard, cancellation, pending-first and adapter tests
  → **62 passed**. Additional real-wrapper route and terminal/cancellation tests
  → **32 passed** in the pending-first/route modules.

## Final verification

| Command | Result |
| --- | --- |
| `-m pytest apps/api/tests tests/integration/test_first_short_runtime.py -q` | **824 passed** |
| `-m pytest packages/creator-domain/tests packages/creator-provider/tests packages/creator-service/tests -q` | **1722 passed**, including real PostgreSQL tests |
| `-m pytest apps/worker-orchestrator/tests -q` | **294 passed** |
| `-m pytest tests/test_package_dependency_parser.py tests/test_package_dependency_cli.py tests/test_package_dependency_compliance.py tests/test_viral_prompts.py tests/test_phase4_providers.py tests/integration/test_studio_proxy_runtime.py -q` | **91 passed** |
| `scripts/check_package_dependencies.py` | **0 diagnostics**, no exemptions |
| `-m ruff check apps packages` | **Passed** |
| `basedpyright --pythonpath /data/GitHub/short-form-studio/.venv/bin/python packages/creator-domain packages/creator-provider packages/creator-service apps/api/src apps/worker-orchestrator` | **0 errors, 0 warnings** |
| `-m compileall -q` on the three changed production files | **Passed** |

Total: **2931 tests passed**. API tests retain one existing event-loop deprecation
warning. Runtime and PostgreSQL tests used the shared disposable database on
`127.0.0.1:55439/short_form_refactor` and Redis on `127.0.0.1:56389/0`, with unique
schemas and queue. The runtime test itself was unchanged and verified separate
Celery rendering, API restart, access control, download, ffprobe, and publishing.

The shared dispatch helper is 110 nonblank/noncomment lines; adapter 71; new test
modules 162 and 54. Existing oversized route/test files received only callback and
fixture migration changes. New code adds no `Any`, casts, or type suppressions;
the shared helper owns pending-first submission and compensation, and existing
public callback surfaces retain compatibility except for the explicitly migrated
task-ID argument. No commits, pushes, subagents, or dependency changes.
