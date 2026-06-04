# Agent Rules

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
- Squash merge preferred for clean history

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

When user needs to view generated artifacts (videos, images, audio):

1. Start HTTP server: `python3 -m http.server <port> --bind 0.0.0.0 --directory <artifact_dir>`
2. Expose externally using ONE of these (in priority order):
   - **localtunnel** (PREFERRED, no auth): `npx -y localtunnel --port <port>`
   - **ngrok** (needs authtoken): `ngrok http <port>` — only if authtoken is configured in ~/.config/ngrok/ngrok.yml
   - **serveo.net** (unreliable): `ssh -R 80:localhost:<port> serveo.net`
3. Verify the URL works: `curl -s -H "Bypass-Tunnel-Reminder: true" <url> -o /dev/null -w "%{http_code}"`
4. Provide the public URL to the user

**IMPORTANT RULES:**
- NEVER ask how to expose — always use localtunnel by default
- ALWAYS verify the URL returns 200 before giving it to the user
- localtunnel requires header `Bypass-Tunnel-Reminder: true` for programmatic access
- If one method fails, immediately try the next one — do NOT ask the user
