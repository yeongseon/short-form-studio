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

## Personal API Keys and Attribution

> **Warning**: The current API key model is designed for **single-user or
> trusted-team deployments only**. It is NOT suitable for multi-user public
> deployments.

### Current Model

- Each user can hold multiple named personal API keys. The `api_keys` table
  binds each key to a `user_id`; only the SHA-256 hash is stored.
- Operators issue keys with `scripts/create_api_key.py --email <user-email>
  --workspace <workspace-slug> --name <key-label>`. Repeating issuance for the
  same email creates another key for the same user. The raw key is displayed
  once for delivery to that user; keep this output out of application logs.
- Clients continue using `X-API-Key` or `Authorization: Bearer`. Workspace
  access comes from that user's memberships; `X-Workspace-Id` selects one of
  those workspaces. Missing/invalid/revoked credentials return 401; unavailable
  or unauthorized workspace selections return 404. Auth database failures
  return 503, including the dependency fallback lookup.
- Request audit entries from `shorts_api.app_factory` include `user_id`,
  `key_id` (the database primary key), and `workspace_id`, alongside method,
  path, response status, and elapsed time. These identify authenticated actions
  reaching request logging, including route-level errors. Raw credentials,
  key hashes, authorization headers, and query strings are not audit fields.
- Authentication middleware rejections occur before request logging; these
  entries are not a comprehensive authentication-attempt ledger. Admin audit
  logging remains a separate authentication domain, described below.
- Revocation is per key: operators set `api_keys.revoked_at` for its `id`.
  Revoked keys cannot authenticate; other keys belonging to the user remain valid.
- Sharing a personal key still makes all holders appear as its owner. In
  particular, a Studio proxy configured with one `API_KEY` attributes all
  browser actions to that key's user, not to distinct humans. Use individually
  provisioned credentials for per-user attribution.
- Keys cannot be scoped to specific operations (read-only, write-only, etc.)

### Implications for Multi-User Deployments

If you need to support untrusted multi-user access:

| Requirement | Current Support | Recommendation |
|-------------|-----------------|----------------|
| Per-user identity | Yes (personal keys) | OAuth2/OIDC for human login |
| Role-based access | No | Implement RBAC layer |
| Audit trail per user | Request logs carry user/key/workspace IDs | Durable audit storage and auth-attempt coverage |
| Key revocation per user | Individual key revocation via DB | Self-service key lifecycle management |
| Rate limiting per user | No | Token-based rate limiting |

### OAuth2/OIDC Roadmap (Not Implemented)

For production deployments with multiple untrusted users:

1. Adopt an **identity provider** (e.g. Authelia or Keycloak)
2. Map identity tokens to workspace membership
3. Issue **per-user, short-lived tokens** instead of long-lived API keys
4. Preserve user attribution in a durable audit trail
5. Retain personal/service API keys for machine-to-machine clients

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
4. **Credential compromise**: A leaked personal key grants its owner's workspace
   access; a shared Studio proxy key exposes that same identity to every holder.

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

## Provider API Key Configuration

### Supported model: server-side environment variables, read-only status surface

Provider API keys (OpenAI, Anthropic, Google, Stability, ElevenLabs, Groq) are
configured **exclusively through server environment variables** and are resolved
at runtime with `os.getenv` only. This is a deliberate security decision, not a
missing feature.

| Property | Behavior |
|----------|----------|
| Source of truth | Server environment variables (`OPENAI_API_KEY`, etc.) |
| Request-time writes | **None** — the API never writes `.env`, a DB, or any secret store from a request |
| Settings surface | `GET /api/creator/settings/api-keys` returns `{provider, label, configured}` only |
| Key values in responses | **Never** — not raw, not masked, not truncated (presence boolean only) |
| Key values in logs | **Never** — no key material is passed to any logger |
| Browser storage | **Never** — the UI holds no provider keys in `localStorage`/`sessionStorage` |
| Rotation | Change the env var and restart: `docker compose restart api worker` |

Write verbs (`POST`/`PUT`/`PATCH`/`DELETE`) on the settings path return `405
Method Not Allowed` and have no side effects. A presence-only contract is
preferred over masked values because a mask still leaks length, prefix, suffix,
or format of the secret.

### CSRF applicability

CSRF protection is **not applicable** to the current creator API because
authentication uses explicit request headers (`X-API-Key` /
`Authorization: Bearer`), not cookies or any browser-auto-attached credential.
A cross-origin page cannot forge those headers, and there are no mutating
settings endpoints. If creator authentication ever moves to cookie/session
credentials, or request-time key-mutation endpoints are introduced, CSRF
protection (or per-request CSRF tokens at the `apps/studio-web/src/api/client.ts`
choke point) becomes required before enabling them.

### Trust model note

The presence booleans reveal which providers are configured to any authenticated
operator. This is intentional and acceptable under the documented single-user /
internal-team trust model; it is not a public endpoint. Self-service key
management from the UI (encrypted server-side storage, admin-scoped rotation,
audit) is explicitly **out of scope** and would be tracked as a separate,
larger secret-management feature.

---

## Artifact Access

Generated artifacts (videos, images, audio) are stored on the local filesystem
under `ARTIFACT_ROOT`. Access is gated by the creator API — artifacts are never
served directly from the filesystem to external clients.

For external preview access during development, use the documented loopback
HTTP server pattern (see `AGENTS.md`). External tunneling requires explicit
user confirmation.
