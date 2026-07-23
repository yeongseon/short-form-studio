# ADR-007: OAuth2/OIDC Integration (Supabase Auth Primary, Auth0 Fallback)

**Status**: Proposed  
**Date**: 2026-07-18  
**Decision makers**: @yeongseon  
**Supersedes**: None (extends ADR-006)

## Context

ADR-006 documented the shared-API-key model as intentional for a single-team deployment, and explicitly named the conditions that should trigger a move to OAuth2:

> Revisit when **any** of these conditions apply:
> - Multiple independent teams/organizations share the instance
> - Public signup is needed
> - Fine-grained per-user permissions required beyond workspace isolation
> - Third-party integrations need scoped access tokens

The project has reached that threshold. A production-readiness review surfaced four blockers that all reduce to the absence of per-user identity:

1. **No per-user audit trail.** Every action is attributed to the workspace, not a person. The `admin.audit` logger records a key fingerprint, not a user.
2. **No per-user rate limiting.** `/api/creator/*` accepts LLM/image/TTS calls with no upper bound per caller. A single leaked key can run unbounded cost.
3. **No per-user billing or quotas.** `workspace_quotas` (migration 027) is a single row per workspace with hardcoded defaults. There is no metered-usage surface that a billing system could read.
4. **No scoped personal access tokens (PATs).** CLI users share the workspace key. Revoking one user requires rotating the key for everyone.

Additionally, `users` (migration 012) was designed for OAuth from day one:

```python
sa.Column("auth_provider", sa.String(length=50), nullable=False, server_default="api_key"),
sa.Column("auth_subject", sa.String(length=255), nullable=False, server_default=""),
sa.UniqueConstraint("auth_provider", "auth_subject", name="uq_users_auth_provider_auth_subject"),
```

This ADR records the decision to add OAuth2/OIDC alongside the existing API key model, without deprecating API keys.

## Decision

**Adopt Supabase Auth (GoTrue) as the primary identity provider. Use Auth0 (Okta) as the managed-SaaS fallback. Both coexist with the existing API key model from ADR-006 via a new `OIDCMiddleware` that runs alongside `ApiKeyMiddleware`.**

### Why Supabase Auth (primary)

| Factor | Rationale |
|---|---|
| Self-hostable | GoTrue is OSS (Apache 2.0). Aligns with the project's self-hostable deployment model. |
| Postgres-native | Same datastore as the application. User metadata lives where the app can join it. |
| Scoped PATs | Supabase Studio ships first-class scoped PAT UI — direct fit for CLI migration. |
| JWT verification | Local JWKS verification. No per-request network call to the IdP. |
| Existing patterns | Production-ready FastAPI + tenancy patterns exist (e.g., `supabase-fastapi-tenancy`). |

Evidence:
- GoTrue self-host README: <https://github.com/supabase/gotrue/blob/971f7c1e372f7d36844ddbcdce9004d252c70095/README.md>
- Scoped PAT UI (Supabase Studio): <https://github.com/supabase/supabase/commit/8ffdcfc145d6731804d623ba028deeba68778e4d>
- FastAPI tenancy pattern with `SET LOCAL`: <https://github.com/skunkworks-powerweave/supabase-fastapi-tenancy/blob/d36d2b76223af958cfb46b321942906ebc875d18/README.md>

### Why Auth0 (fallback)

For deployments that prefer a managed IdP over self-hosting GoTrue. Auth0 publishes an official FastAPI SDK (`auth0-fastapi-api`) with `require_auth()`, DPoP support, and JWKS caching.

Evidence: <https://github.com/auth0/auth0-fastapi-api/blob/d448b4d38fb18eaa0311d3104ead58ac7df06411/README.md>

### Coexistence model

```
Client (browser)  ── Authorization: Bearer <JWT>  ──┐
                                                     │
Client (CLI/script) ── X-API-Key: <key> ────────────┤  →  ApiKeyMiddleware (unchanged)
                                                     │       → if key present, resolve, done
                                                     │
                                                     └─→  OIDCMiddleware (new, runs after)
                                                              → if Bearer JWT present, verify, resolve
                                                              → sets same CurrentUser shape
```

Both middleware set `request.state.user` and the `_current_user_ctx` ContextVar to the same `CurrentUser` dataclass. The existing DI helpers (`require_run_access`, `require_project_access`, `require_workspace_access`) work unchanged for both auth methods.

**Precedence rule:** `X-API-Key` takes precedence over `Authorization: Bearer` when both are present. This preserves the behavior pinned in `tests/test_auth.py::test_x_api_key_takes_precedence`.

## Alternatives considered

| Provider | Verdict |
|---|---|
| **Auth0** | Strong managed option, but SaaS-only. Adopted as the documented fallback, not primary, because self-hosting is a project requirement. |
| **Clerk** | Excellent React SDK, but no self-host path and scoped PATs would have to be built in-app. Rejected as primary. |
| **Keycloak** | Powerful OIDC IdP, but operationally heavy (Java, separate DB, admin UI). Overkill for this project's scope. |
| **Authelia** | Already referenced in `docs/SECURITY.md`, but its primary role is reverse-proxy SSO. App-level OIDC provider support is less mature than GoTrue. |

## Migration plan

Three phases. Each phase is independently deployable and reversible.

### Phase 1 — Dual-auth (non-breaking)

- Add `apps/api/src/shorts_api/oidc.py`: JWKS verifier + `OIDCMiddleware`.
- Register `OIDCMiddleware` in `app_factory.py` **after** `ApiKeyMiddleware`.
- Extend `CurrentUser` with `auth_method: Literal["api_key", "jwt"] = "api_key"` for audit logging (default preserves backward compat for existing construction sites).
- Add `jwt_client` fixture to `conftest.py` alongside the existing `client`.
- Document `SUPABASE_AUTH_URL` / `SUPABASE_JWKS_URL` / `SUPABASE_JWT_AUDIENCE` env vars.
- **Acceptance gate:** existing 577 tests still pass; new tests cover JWT verification + both-auth-method coexistence.
- **Rollback:** remove `OIDCMiddleware` registration. Zero client impact.

### Phase 2 — Frontend + CLI migration

- Add `apps/studio-web/src/auth/` Supabase client wrapper.
- Migrate `studio-web` from nginx-injected `X-API-Key` to browser session.
- Document CLI migration: workspace shared key → user-scoped PAT issued via Supabase Studio.
- Monitor JWT adoption via the `auth_method` audit field.
- **Rollback:** revert frontend; nginx `X-API-Key` injection remains intact.

### Phase 3 — Optional API key deprecation (future)

- Only after metrics show all interactive clients use JWTs.
- Keep `ApiKeyMiddleware` for service-to-service (worker → API) and bootstrap (`scripts/create_api_key.py`).
- This phase is **not** part of this ADR's acceptance criteria.

## Files to be touched

| File | Phase | Change |
|---|---|---|
| `apps/api/src/shorts_api/oidc.py` | 1 | NEW — JWKS verifier + `OIDCMiddleware` |
| `apps/api/src/shorts_api/app_factory.py` | 1 | Register `OIDCMiddleware` after `ApiKeyMiddleware` |
| `apps/api/src/shorts_api/auth.py` | 1 | Extend `CurrentUser` with `auth_method: Literal["api_key", "jwt"] = "api_key"` |
| `apps/api/tests/conftest.py` | 1 | Add `jwt_client` fixture |
| `apps/studio-web/src/auth/` | 2 | NEW — Supabase client wrapper |
| `apps/studio-web/nginx.conf.template` | 2 | Conditional `X-API-Key` injection (both modes documented) |
| `docs/SECURITY.md` | 1 | Add "OAuth2/OIDC domain" alongside API-key and admin domains |
| `docs/adr/006-api-key-authentication-model.md` | 1 | Cross-link to this ADR; note ADR-006 remains in force for service-to-service |
| `scripts/create_api_key.py` | 2 | Update docs/help text to recommend user-scoped PATs from Supabase Studio for interactive CLI use |
| `scripts/create_api_key.py` | 3 | Bootstrap-only (service accounts) once PATs are the default |

## Constraints honored

- **Anti-enumeration** (AGENTS.md): "always return 404 (never 403) for unauthorized access." The `OIDCMiddleware` MUST return 401 for missing/invalid tokens and 404 for unauthorized workspace access — same as `ApiKeyMiddleware`. Verified by tests.
- **Loopback binding** (SECURITY.md): "API port bound to `127.0.0.1` (never `0.0.0.0`)." OIDC callback URLs target the reverse proxy, not the API directly. The API stays loopback.
- **DI helper contract** (AGENTS.md): "All `/api/creator/` routes MUST use one of: `require_run_access` / `require_project_access` / `require_workspace_access`." These helpers continue to work for both auth methods because both middleware set the same `CurrentUser`.
- **TDD + Oracle Review Workflow** (AGENTS.md): Applies to the **implementation PRs** that follow this ADR, not to this ADR itself.

## Open questions

| Question | Recommendation |
|---|---|
| Self-host GoTrue in docker-compose, or require managed Supabase? | Support both via env vars. Add a docker-compose profile (similar to the existing `gpu` profile) for self-hosted GoTrue; managed via `SUPABASE_URL`. |
| Add Postgres RLS now? | Defer. RLS is a separate hardening layer and is not required for this ADR's auth migration. |
| Migrate admin auth (`X-Admin-Key`) to OAuth? | No. Admin auth stays as ADR-006 specifies. Operator-only, separate trust domain. |

## Consequences

**Positive:**
- Per-user identity enables per-user audit, rate limiting, billing, and scoped PATs.
- The `users.auth_provider` / `auth_subject` columns (migration 012) finally get used as designed.
- No client breakage — API keys continue to work throughout.

**Negative:**
- Additional infrastructure (self-hosted GoTrue) or vendor cost (managed Supabase).
- Double maintenance: both `ApiKeyMiddleware` and `OIDCMiddleware` must be kept correct until Phase 3.
- Test surface grows: every creator route test needs both API-key and JWT variants where behavior diverges.

**Neutral:**
- `conftest.py` grows a `jwt_client` fixture. Existing `client` fixture unchanged.
- Audit log shape gains an `auth_method` field.

## References

- [ADR-006: API Key Authentication Model](./006-api-key-authentication-model.md) — remains in force for service-to-service and admin auth.
- [`docs/SECURITY.md`](../SECURITY.md) — network exposure policy, anti-enumeration, deployment checklist.
- [AGENTS.md](../../AGENTS.md) — TDD + Oracle Review Workflow that governs implementation PRs.
