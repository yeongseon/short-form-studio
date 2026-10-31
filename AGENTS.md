# Agent Rules

## TDD for All Implementation Work

All feature, bug-fix, and refactoring implementation MUST use TDD:

1. Write behavior or regression tests before changing production code.
2. Run them and confirm they fail for the intended reason (Red).
3. Implement the minimum change needed to pass (Green).
4. Refactor while keeping the tests green; do not weaken assertions to pass.
5. Run relevant regression tests, type checks, lint, and builds. Include the
   failing and passing commands/results in the implementation handoff or PR.

For existing behavior, add characterization tests before refactoring and record
the passing baseline; new or changed behavior still requires a failing test first.
Documentation-only changes use content/link checks rather than artificial tests.
The additional security and production-hardening gates below still apply.

## TDD + Oracle Review Workflow

All security-critical and production-hardening changes MUST follow this workflow:

### 1. Write Tests First (TDD)
- Write failing security boundary tests BEFORE implementing fixes
- Tests must cover: access control, IDOR prevention, anti-enumeration (404 not 403), auth bypass attempts
- Run tests to confirm they fail for the right reason

### 2. Implement Fixes
- Fix the minimum code needed to make tests pass
- Follow existing codebase patterns (dependency injection, access control via `require_run_access`/`require_project_access`)
- Never suppress type errors

### 3. Verify All Tests Pass
- Run full test suite: `cd apps/api && python3 -m pytest tests/ -v`
- Zero failures required before proceeding

### 4. Oracle Review
- Submit code for Oracle review with detailed criteria
- Score must reach **100/100** before merge
- Scoring breakdown (10 sections, 10 points each):
  - IDOR Protection, Auth Completeness, Error Handling, Signal Handling
  - Input Validation, Type Safety, Test Coverage, Code Quality
  - Race Conditions, Defense in Depth
- Deductions: Critical (-20), Major (-10), Minor (-2), Advisory (0)

### 5. Fix and Re-review
- Address all Critical and Major findings
- Re-run Oracle review until 100/100
- Minor findings: fix if straightforward, document if intentional

### 6. Merge
- Only merge after Oracle 100/100 AND full test suite green
- Required CI must also be green on the exact final head SHA (see **CI Failure Handling** below)
- Squash merge preferred for clean history

## CI Failure Handling

This section follows the TDD workflows above and does not relax any of their gates
(full API suite, Oracle 100/100, 404 anti-enumeration). It applies whenever CI fails on a
pull request or during implementation work.

### Classify the cause first

Read the failing job log and reproduce the failure locally when possible. Then label it:

- **Change-related regression**: the current change caused it.
- **Pre-existing defect**: a real defect that already existed and was exposed by the change or by CI.
- **Infrastructure, external dependency or flaky failure**: runner, registry, network, an external
  service, or a nondeterministic test.
- **Test/environment prerequisite gap**: a test needs something (FFmpeg, an import path, a Compose
  fixture) that CI does not declare.

### Change-related regressions

- Fix them in the same PR. Add or strengthen a regression test that fails for the intended reason
  first (Red), then passes (Green).
- Re-run the focused tests, then every required CI check.
- Flow: implement → CI fails → reproduce → regression test → fix → focused tests → full required CI →
  exact final head SHA green → review → merge.

### Newly discovered defects (issue-first)

When CI exposes a defect that the change did not cause:

1. Check whether an issue already covers it.
2. If not, open an issue first (or add it explicitly to the current issue's scope), with the evidence.
3. If it affects correctness, security, data integrity, or release readiness, fix it before merging.
4. If it does not block, it may be deferred explicitly: record the evidence and a priority on the
   issue and link it from the PR.
5. The minimal fix needed to finish the current PR safely may ride in the same PR once the issue is
   linked. Never mix in unrelated refactors or cleanup.

### Infrastructure, external and flaky failures

- Do not work around them in application code.
- Confirm whether the failure reproduces and what the external cause is.
- If the CI environment or a fixture is at fault, fix it and add a check that would catch a recurrence.
- A green re-run does not count as a fix for a flaky or infrastructure failure.

### Prerequisite gaps

Declare what the test really needs and keep the test. Example: a real-media render test fails on the
runner because FFmpeg is missing. Install FFmpeg and ffprobe in the CI job, add an executable and
version check, keep the render test, and re-run the full CI. Do not skip the test.

### Never make CI green by

- weakening an assertion
- adding a skip or xfail marker without evidence
- disabling a required check
- lowering a coverage threshold
- suppressing type or lint errors
- deleting a failing test
- removing a security or authorization check
- retrying a failing job until it passes in order to hide the failure

### Merge gate

- Merge only when every required check (lint, tests, docker/runtime, security, review gates, and
  anything else the repository requires) is green on the **exact final head SHA** of the PR.
- A green result from an earlier SHA is not evidence for the final head. After every push, wait for
  the checks on the new head.
- Documentation-only changes are verified with content and consistency checks (diff hygiene, links,
  referenced paths and commands) instead of artificial tests.

This is a working rule, not automation: it does not add a CI auto-repair bot or unlimited retries.

## Access Control Pattern

All `/api/creator/` routes MUST use one of:
- `require_run_access(run_id)` — returns `(CurrentUser, PipelineRun)`, verifies workspace ownership
- `require_project_access(project_id)` — returns `(CurrentUser, Project)`, verifies workspace ownership
- `require_workspace_access(workspace_id)` — verifies user membership

Anti-enumeration: always return 404 (never 403) for unauthorized access.

## Test Fixture Pattern

Test files using routes with access control dependencies must add overrides:

```python
from shorts_api.auth import CurrentUser, require_run_access
from shorts_api.main import app

async def _require_run_access(run_id: int) -> tuple[CurrentUser, StubPipelineRun]:
    run = run_svc.runs.get(run_id)
    if run is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Run not found")
    return CurrentUser(user_id=1, workspace_id=1), run

app.dependency_overrides[require_run_access] = _require_run_access
yield ...
app.dependency_overrides.pop(require_run_access, None)
```

## External Access (File Serving)

When the user needs to view generated artifacts (videos, images, audio):

1. Start an HTTP server bound to **loopback only**, scoped to the artifact directory:
   `python3 -m http.server <port> --bind 127.0.0.1 --directory <artifact_dir>`
2. Give the user the loopback URL (e.g. `http://127.0.0.1:<port>/<file>`). This is the default path — no external exposure is performed automatically.
3. **External exposure requires explicit user confirmation.** If (and only if) the user asks to expose an artifact beyond the local machine, offer ONE of:
   - **localtunnel** (no auth): `npx -y localtunnel --port <port>`
   - **ngrok** (needs authtoken in `~/.config/ngrok/ngrok.yml`): `ngrok http <port>`
   - **serveo.net** (unreliable): `ssh -R 80:localhost:<port> serveo.net`
4. (Only if Step 3 was followed) Verify the public URL returns 200 before handing it over: `curl -s -H "Bypass-Tunnel-Reminder: true" <url> -o /dev/null -w "%{http_code}"`
5. Serve ONLY the artifact directory — never the repository root or any directory containing source, secrets, or `.env`.

**IMPORTANT RULES (security):**
- **ALWAYS bind to `127.0.0.1`** (loopback). NEVER use `--bind 0.0.0.0`. This aligns with the loopback policy in `docs/SECURITY.md`.
- **NEVER expose externally without asking the user first.** Do not run localtunnel/ngrok/serveo automatically.
- When exposing, prefer localtunnel (no signup/authtoken required); if it fails, ask the user before trying the next method.
- Always verify a public URL returns 200 before giving it to the user.
- localtunnel requires header `Bypass-Tunnel-Reminder: true` for programmatic access.
