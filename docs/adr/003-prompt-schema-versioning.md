# ADR-003: Prompt, Schema, and Tool Versioning in creator-provider

**Status**: Accepted  
**Date**: 2026-05-12  
**Decision makers**: @yeongseon

## Context

`creator-provider` previously kept prompt text fragments and request-shape definitions inline in provider classes. This couples behavioral content (prompt text, schema values, tool/message structure) with transport logic (HTTP request handling), making versioned rollout and controlled changes harder.

Issue #380 requires these assets to be extracted into dedicated versioned files.

## Decision

Adopt a file-based versioning strategy inside `packages/creator-provider/creator_provider/`:

- `prompts/<version>/` for prompt text assets (`.txt`)
- `schemas/<version>/` for JSON schema/config assets (`.json`)
- `tools/<version>/` for tool/message definition assets (`.json`)

Add a single loader module, `creator_provider/versioned_assets.py`, with:

- `get_prompt(name, version="v1")`
- `get_schema(name, version="v1")`
- `get_tool_definition(name, version="v1")`

The loader resolves files by convention and caches loaded values.

## Versioning Strategy

1. **Immutable versions**: once an asset is released under `v1`, do not mutate content in place for behavior-changing updates.
2. **New behavior => new version**: create `v2` (or higher) directories for any semantic changes.
3. **Selection by caller**: runtime defaults to `v1` and can opt into newer versions explicitly.
4. **Transport logic stays stable**: provider classes consume loaded assets but keep networking/error handling code unchanged.

## Initial Extraction Scope

The initial `v1` extraction includes:

- Prompt asset: SD Local quality-prefix text
- Schema assets: SD Local request defaults/allowlist and Stability aspect-ratio map
- Tool definition asset: shared LLM user-message template shape

This preserves current behavior while separating content/config from provider implementation.

## Consequences

- Prompt/schema/tool changes become reviewable as file diffs, independent of HTTP logic.
- It is easier to stage and test new prompt/schema versions.
- Providers remain dependency-light (no new external packages).
- Future structured-output schemas can follow the same layout without architectural changes.
