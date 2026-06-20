# Security Model

This document describes the authentication architecture, trust boundaries,
and deployment constraints for Short Form Studio.

---

## Authentication Domains

The system uses **two separate authentication domains**:

| Domain | Path Prefix | Credential | Header |
|--------|-------------|------------|--------|
| Creator API | `/api/creator/*` | DB-backed API key (SHA-256 hashed) | `X-API-Key` or `Authorization: Bearer` |
| Admin API | `/api/admin/*` | Environment variable (`ADMIN_API_KEY`) | `X-Admin-Key` |

These credentials are **not interchangeable**. A valid creator API key cannot
access admin endpoints, and vice versa.

### Defense-in-Depth

Admin authentication is enforced at **two layers**:

1. **Middleware layer** (`ApiKeyMiddleware`): Validates `X-Admin-Key` against
   `ADMIN_API_KEY` before the request reaches any route handler. Returns 401
   if key is missing or env var is unset; returns 403 if key doesn't match.

2. **Router dependency layer** (`Depends(require_admin)`): All admin routes
   include this dependency as a secondary check with additional production
   safeguards (minimum key length enforcement, timing-safe comparison).

This ensures that even if a new admin sub-route is added without the proper
dependency, the middleware still blocks unauthenticated access.

---

## Shared API Key Limitations

> **Warning**: The current API key model is designed for **single-user or
> trusted-team deployments only**. It is NOT suitable for multi-user public
> deployments.

### Current Model

- One workspace has one or more API keys
- All users sharing a key have **identical permissions** within that workspace
- There is no per-user audit trail at the key level (all actions appear as
  the same user)
- Keys cannot be scoped to specific operations (read-only, write-only, etc.)

### Implications for Multi-User Deployments

If you need to support untrusted multi-user access:

| Requirement | Current Support | Recommendation |
|-------------|-----------------|----------------|
| Per-user identity | No (shared key) | Add OAuth2/OIDC integration |
| Role-based access | No | Implement RBAC layer |
| Audit trail per user | No | Per-user tokens with identity binding |
| Key revocation per user | Partial (revoke entire key) | Per-user token management |
| Rate limiting per user | No | Token-based rate limiting |

### Recommended Production Architecture (Multi-User)

For production deployments with multiple untrusted users:

1. Place an **identity provider** (Keycloak, Auth0, Supabase Auth) in front
2. Map identity tokens to workspace membership
3. Issue **per-user, short-lived tokens** instead of long-lived API keys
4. Add audit logging that captures the authenticated user identity

Until these are implemented, treat the current system as a **team-internal
tool** where all key holders are trusted.

---

## Network Exposure Policy

> **Critical**: The API server (port 8000) must **NEVER** be directly exposed
> to the public internet.

### Required Architecture

```
Internet → Reverse Proxy (nginx/Caddy/Traefik) → localhost:8000 (API)
                    ↓
              TLS termination
              Rate limiting
              IP allowlisting
              Request size limits
```

### Default Port Bindings

The `docker-compose.yml` binds all backend services to `127.0.0.1` only:

```yaml
api:
  ports:
    - "127.0.0.1:8000:8000"   # API — loopback only

postgres:
  ports:
    - "127.0.0.1:5432:5432"   # DB — loopback only

redis:
  ports:
    - "127.0.0.1:6379:6379"   # Cache — loopback only
```

The `docker-compose.local-server.yml` override maintains this policy:
- `studio-web` is exposed on `0.0.0.0` for LAN access (UI only)
- API, Postgres, and Redis remain on `127.0.0.1`

### Why Direct Exposure is Dangerous

1. **No TLS**: The API speaks plain HTTP. Direct exposure means credentials
   travel in cleartext.
2. **No rate limiting**: Without a reverse proxy, the API has no protection
   against brute-force or denial-of-service attacks.
3. **No request filtering**: Large payloads, malformed requests, and slow
   clients hit the API directly.
4. **Single credential**: If the shared API key leaks, there's no network-level
   barrier to full access.

### Deployment Checklist

Before exposing the system to any network:

- [ ] API port bound to `127.0.0.1` (never `0.0.0.0`)
- [ ] Reverse proxy with TLS configured
- [ ] `CORS_ORIGINS` set to specific allowed origins (not `*`)
- [ ] `ADMIN_API_KEY` set to a strong value (16+ characters)
- [ ] `POSTGRES_PASSWORD` changed from default
- [ ] `ENVIRONMENT=production` set (enables startup safety checks)
- [ ] Firewall rules block direct access to ports 8000, 5432, 6379

### CI Validation

The CI workflow validates that `docker-compose.yml` does not expose the API
on `0.0.0.0`. If you need LAN access for the API during development, use the
`docker-compose.local-server.yml` override with explicit acknowledgment of
the security implications.

---

## Admin API Security Controls

### ADMIN_API_KEY Requirements

| Environment | Minimum Length | Behavior if Unset |
|-------------|---------------|-------------------|
| Development | None | Returns 401 on admin requests |
| Production | 16 characters | API refuses to start (fail-fast) |

### Rate Limiting

Destructive admin operations (unstick run, clear cache) are rate-limited to
**10 operations per minute** per admin key. Rate limiting uses Redis when
available, with an in-memory fallback.

### Audit Logging

All admin mutations are logged to the `admin.audit` logger with:
- Action type
- Target resource
- Key fingerprint (first 8 chars of SHA-256)
- Request ID
- Source IP
- Unique audit ID (UUID)

### Safety Guards

- Cache clear operations must match an allowlist of key prefixes
- Dangerous patterns (`*`, `*:*`, empty) are rejected
- Destructive operations require `X-Confirm-Action: yes` header

---

## Artifact Access

Generated artifacts (videos, images, audio) are stored on the local filesystem
under `ARTIFACT_ROOT`. Access is gated by the creator API — artifacts are never
served directly from the filesystem to external clients.

For external preview access during development, use the documented HTTP server
+ localtunnel pattern (see `AGENTS.md`).
