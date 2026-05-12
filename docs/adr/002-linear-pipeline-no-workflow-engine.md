# ADR-002: Linear Pipeline, No Workflow Engine

**Status**: Accepted  
**Date**: 2026-05-12  
**Decision makers**: @yeongseon

## Context

The video production pipeline has a clear linear stage flow:

```
IDEA_READY → SCRIPT_GENERATING → SCRIPT_REVIEW
  → VISUAL_PLAN_SETUP → VISUAL_PLAN_GENERATING → VISUAL_PLAN_REVIEW
  → VISUAL_ASSET_GENERATING → VISUAL_ASSET_REVIEW
  → AUDIO_GENERATING → SUBTITLE_GENERATING
  → RENDER_GENERATING → FINAL_REVIEW → PUBLISHED
```

Each stage has a dedicated:
- **Service method** in `creator-service` (business logic)
- **API route** in `apps/api` (HTTP trigger)
- **Celery task** in `apps/worker-orchestrator` (async execution)
- **Stage enum** in `creator-domain` (state machine)

It would be tempting to abstract this into a generic DAG/workflow engine. This ADR explains why we deliberately do not.

## Decision

**Keep the pipeline linear and explicit. Do not introduce a generic workflow engine.**

### Design principles

1. **Explicit over abstract**: Each stage is a named function, not a node in a graph config. This makes the code greppable, debuggable, and obvious.

2. **One path**: There is one production path through the pipeline. Branching (e.g., retry a stage, skip a stage) is handled by explicit state transitions, not graph traversal.

3. **Human-in-the-loop gates**: Review stages (`*_REVIEW`) are intentional pauses. They are not "conditional edges" — they are first-class stages.

4. **Stage = unit of work**: Each stage maps 1:1 to a Celery task via `task_runner.py`. The common runner handles state transitions, error handling, and rollback uniformly.

### When to reconsider

Revisit this decision when **3 or more** of these conditions are met:
- Multiple distinct pipeline types exist (not just video)
- Stages need dynamic ordering per pipeline instance
- Non-linear dependencies between stages (DAG, not chain)
- External teams need to define custom pipelines

Until then, adding a workflow engine is premature abstraction.

## Current state audit

No generic workflow abstractions exist in the codebase. The pipeline is implemented as:
- `PipelineStage` enum in `creator-domain` (explicit stage list)
- `task_runner.py` common runner (uniform execution, not routing)
- Route handlers that dispatch to specific tasks (not a generic dispatcher)

This is the correct level of abstraction for a single-pipeline product.

## Consequences

- New stages are added by: creating enum value + service method + route + task + tests
- No YAML/JSON pipeline definitions
- No dynamic stage ordering
- The pipeline is "boring" — and that's the point
