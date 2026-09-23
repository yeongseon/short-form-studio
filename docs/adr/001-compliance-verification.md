# Issue 621 implementation evidence

Worktree: `/tmp/opencode/short-form-refactor`.

All pytest commands below used `/data/GitHub/short-form-studio/.venv/bin/python`
with `PYTHONPATH` pointing at this worktree's `packages/creator-domain`,
`packages/creator-service`, `packages/creator-provider`, `apps/api/src`, and
`apps/worker-orchestrator`. The worktree-local `.venv` lacks pytest.

## Red and characterization

- Before production moves, dispatch service, atomicity, lightweight, typed errors,
  voice preset, actionable errors, and telemetry suites: **128 passed**.
- All eight worker-call wrapper argument characterizations: **8 passed** before
  the dispatch split.
- `scripts/check_package_dependencies.py`: **7 blocking diagnostics**, exit 1.
- `tests/test_package_dependency_compliance.py` and
  `packages/creator-service/tests/test_domain_provider_contracts.py`: **7 failed**
  before implementation (illegal production edges and missing domain contracts).
- Real `asyncpg.Record` authentication regression: **1 failed** before normalizing
  the row to a dictionary at the Pydantic boundary. This was the blocker found by
  the real first-short acceptance run, not a dispatch failure.
- Real bound Celery task lightweight regression: **1 failed, 3 passed** before
  correcting bound-method invocation in the application adapter.

## Green

| Command (after interpreter prefix) | Result |
| --- | --- |
| `scripts/check_package_dependencies.py` | **0 diagnostics**, exit 0; unchanged checker, no exemptions |
| `-m pytest packages/creator-domain/tests packages/creator-provider/tests packages/creator-service/tests -q` | **1714 passed, 8 skipped** |
| `-m pytest apps/api/tests tests/integration/test_first_short_runtime.py -q` | **791 passed** |
| `-m pytest apps/worker-orchestrator/tests -q` | **294 passed** |
| `-m pytest tests/test_package_dependency_parser.py tests/test_package_dependency_cli.py tests/test_package_dependency_compliance.py tests/test_viral_prompts.py tests/integration/test_studio_proxy_runtime.py -q` | **73 passed** |
| `-m pytest tests/test_phase4_providers.py -v` | **18 passed**, 190.69 seconds |
| `-m pytest packages/creator-service/tests/test_postgres_media_asset_storage.py packages/creator-service/tests/test_dispatch_typed_exceptions.py -q` | **18 passed**, including all 8 previously skipped PostgreSQL tests |
| `-m ruff check apps packages tests/test_package_dependency_compliance.py scripts/check_package_dependencies.py` | **Passed** |
| `basedpyright --pythonpath /data/GitHub/short-form-studio/.venv/bin/python packages/creator-domain packages/creator-provider packages/creator-service apps/api/src apps/worker-orchestrator` | **0 errors, 0 warnings** |
| `-m compileall -q packages/creator-domain/creator_domain packages/creator-service/creator_service packages/creator-provider/creator_provider apps/api/src/shorts_api apps/worker-orchestrator` | **Passed** |

The real-runtime commands set `FIRST_SHORT_TEST_DATABASE_URL` and
`MEDIA_ASSET_TEST_DATABASE_URL` to the shared disposable PostgreSQL service at
`127.0.0.1:55439/short_form_refactor`; `FIRST_SHORT_TEST_REDIS_URL` uses
`redis://127.0.0.1:56389/0`. Tests create/drop unique schemas and use an isolated
worker queue. The first-short test passed twice after the authentication fix.
It verifies API restart, explicit timeline approval, foreign-workspace 404s,
separate Celery execution, rendered MP4 download/ffprobe, and final publishing.

## Verification notes

- API and worker suites must run separately: their existing `tests.conftest`
  package names collide in a combined pytest invocation.
- The root provider suite exceeded the initial 120-second command timeout; its
  dedicated 300-second run passed all 18 tests.
- Expanding lint beyond the normal `apps packages` scope finds six existing F541
  findings in untouched `scripts/generate_ssul_shorts.py`.
- LSP tooling cannot inspect this external worktree from the harness cwd;
  standalone basedpyright supplied diagnostics with the correct interpreter.
- New dispatch production modules are 34–147 nonblank/noncomment lines. The
  existing registry catalog table and legacy test modules remain larger.
- Public wrappers keep their existing argument signatures intentionally. Domain
  submissions and protocols replace new untyped boundaries; no new `Any`, casts,
  or type suppressions were added. Compensation catches retain fail-closed and
  best-effort rollback behavior, with existing logging conventions.
- `app_factory.py` was changed only to import and call dispatch initialization.
  No commits, pushes, subagents, or dependency upgrades were used.
