# ADR-006: API Key Authentication Model

**Status**: Accepted  
**Date**: 2026-05-12  
**Decision makers**: @yeongseon

## Context

The platform needs authentication for two distinct audiences:

1. **Creator API** (`/api/creator/*`): End users producing videos via the UI or programmatic clients.
2. **Admin API** (`/api/admin/*`): Operators managing workspaces, users, and system configuration.

OAuth2/OIDC is the ideal long-term solution for multi-user deployments, but the current deployment model is single-team (one workspace). A simpler scheme was chosen that can coexist with OAuth2 later.

## Decision

**Use DB-backed API keys for creator access and a static environment key for admin access.**

### Creator authentication

```
Client → X-API-Key: <key>  (or Authorization: Bearer <key>)
     ↓
Middleware: SHA-256(key) → lookup in `api_keys` table
     ↓
Result: CurrentUser(user_id, workspace_id)
```

- Keys are stored as SHA-256 hashes — plaintext never persisted
- Each key is bound to a `user_id` and `workspace_id`
- Multi-workspace users specify `X-Workspace-Id` header for context
- Keys are created via `scripts/create_api_key.py` (bootstrap) or admin API
- Revocation: delete the key row → immediate effect (no token expiry)

### Admin authentication

```
Client → X-Admin-Key: <key>
     ↓
Compare: constant-time compare against ADMIN_API_KEY env var
     ↓
Result: admin access granted (no user context)
```

- Single shared key set via `ADMIN_API_KEY` environment variable
- Production enforces minimum 16 characters at startup
- Admin routes are a separate router with independent middleware
- No DB lookup — fast and infrastructure-independent

### Anti-enumeration

All access control violations return **404 (Not Found)**, never 403 (Forbidden). This prevents resource enumeration attacks:

```python
# Correct — attacker cannot distinguish "exists but denied" from "does not exist"
async def require_run_access(run_id: int) -> tuple[CurrentUser, PipelineRun]:
    run = await get_run(run_id)
    if run is None or run.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return current_user, run
```

### Why not OAuth2/JWT from the start

| Factor | Decision rationale |
|---|---|
| Team size | Single team — shared API key is sufficient |
| Deployment model | Self-hosted, private network — no public user registration |
| Complexity | OAuth2 requires identity provider setup, token refresh, PKCE flow |
| Migration path | API keys coexist with OAuth2 — add OAuth2 middleware later without breaking existing keys |

### When to add OAuth2

Revisit when **any** of these conditions apply:
- Multiple independent teams/organizations share the instance
- Public signup is needed
- Fine-grained per-user permissions required beyond workspace isolation
- Third-party integrations need scoped access tokens

## Access control helpers

Three dependency-injection helpers enforce workspace ownership:

| Helper | Returns | Use case |
|---|---|---|
| `require_run_access(run_id)` | `(CurrentUser, PipelineRun)` | Run-scoped routes |
| `require_project_access(project_id)` | `(CurrentUser, Project)` | Project-scoped routes |
| `require_workspace_access(workspace_id)` | `CurrentUser` | Workspace-scoped routes |

All verify that the authenticated user's workspace matches the resource's workspace.

## Consequences

- API keys are the sole auth mechanism until OAuth2 is added
- Key rotation requires generating a new key + revoking old one (no automatic rotation)
- Admin key must be rotated by changing the env var and restarting the API
- Workspace isolation is enforced at the route level, not the DB query level
- Public-facing deployments MUST add a reverse proxy with TLS — keys travel in headers
