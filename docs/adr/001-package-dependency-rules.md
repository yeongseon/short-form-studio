# ADR-001: Package Dependency Rules

**Status**: Accepted  
**Date**: 2026-05-12  
**Decision makers**: @yeongseon

## Context

The monorepo has four internal packages and two application layers. As the project grows, unconstrained cross-dependencies would create circular imports, tight coupling, and difficult-to-test code.

## Decision

The dependency graph flows **strictly downward**:

```
apps/api  ─┬─→ creator-service ──→ creator-domain
            └─→ creator-provider ──→ creator-domain

apps/worker ─┬─→ creator-service ──→ creator-domain
             └─→ creator-provider ──→ creator-domain
```

### Rules

1. **`creator-domain`** is the leaf package. It has **zero** internal dependencies. It defines entities, value objects, enums, and port interfaces.

2. **`creator-service`** depends on `creator-domain` only. It implements use cases, storage adapters, and business logic.

3. **`creator-provider`** depends on `creator-domain` only. It implements LLM, Image, TTS, and STT provider adapters. It does **NOT** depend on `creator-service`.

4. **`apps/api`** and **`apps/worker-orchestrator`** depend on both `creator-service` and `creator-provider`. They are the composition root where dependencies are wired together.

5. **No lateral dependencies**: `creator-service` and `creator-provider` must never import from each other.

6. **No upward dependencies**: packages must never import from apps.

### Why provider does NOT depend on service

Providers are I/O adapters (HTTP calls to external APIs). Services are business logic orchestrators. Keeping them independent allows:
- Testing providers without mocking business logic
- Swapping providers without touching service code
- Deploying provider updates independently

## Verification

Check for violations manually:

```bash
# Should return empty (no service imports in provider)
grep -r "from creator_service" packages/creator-provider/ || echo "Clean"

# Should return empty (no provider imports in service)
grep -r "from creator_provider" packages/creator-service/ || echo "Clean"

# Should return empty (no app imports in packages)
grep -r "from shorts_api\|from tasks" packages/ || echo "Clean"
```

A CI lint step can automate this by adding the above checks to the test job.

## Consequences

- New shared types/interfaces must go in `creator-domain`, not copied across packages
- If a service needs provider functionality, it must go through a port interface defined in domain
- Apps are the only place where service + provider can be combined
