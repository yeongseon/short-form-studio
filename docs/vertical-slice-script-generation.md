# Vertical Slice: Script Generation

This document traces the script-generation flow end-to-end across frontend, API, worker orchestration, draft storage, and review approval.

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant FE as Frontend\n`useRunActions.handleGenerate`\n`POST /runs/{id}/generate-script`
    participant API as API Route\n`creator_runs_core.generate_script_trigger`
    participant DIS as Dispatch Service\n`dispatch_generate_script` + CAS
    participant Q as Celery Queue
    participant WK as Worker Task\n`tasks/generate_script.generate_script`
    participant ST as Script Storage\n`script_service.save_draft`
    participant RUN as Run Storage\n`run_service` stage updates
    participant GET as API Route\n`GET /runs/{id}/script`
    participant REV as API Route\n`POST /runs/{id}/approve-script`

    U->>FE: Click Generate
    FE->>API: POST generate-script (model_key, instructions)
    API->>DIS: cas_dispatch_with_rollback(... target=SCRIPT_GENERATING)
    DIS->>RUN: conditional_update_run IDEA_READY/SCRIPT_REVIEW -> SCRIPT_GENERATING
    DIS->>Q: enqueue generate_script task
    DIS-->>FE: 202 {task_id, run_id, current_stage=SCRIPT_GENERATING}

    Q->>WK: execute generate_script(run_id, idea_brief, model_key, instructions)
    WK->>ST: save_draft(source_type=generated_by_model, markdown_content=generated)
    WK->>RUN: run_task success transition -> SCRIPT_REVIEW

    FE->>GET: GET /runs/{id}/script
    GET->>ST: get_active_draft(run_id)
    GET-->>FE: 200 {script, structured_script, version}

    U->>FE: Click Approve Script
    FE->>REV: POST /runs/{id}/approve-script
    REV->>RUN: approve_and_advance SCRIPT_REVIEW -> VISUAL_PLAN_SETUP
    REV-->>FE: 200 updated run
```

## Step-by-Step Flow

1. Frontend trigger
   - `apps/studio-web/src/pages/project/useRunActions.ts` (`handleGenerate`) calls `POST /api/creator/runs/{run_id}/generate-script`.
2. API validation and dispatch
   - `apps/api/src/shorts_api/routes/creator_runs_core.py` validates stage and model key, resolves idea brief from project, then calls `cas_dispatch_with_rollback(...)`.
3. Task dispatch and CAS guard
   - `packages/creator-service/creator_service/task_dispatch_service.py` performs a compare-and-swap stage update to `SCRIPT_GENERATING`, enqueues `tasks.generate_script.apply_async`, and returns the task id.
4. Worker execution
   - `apps/worker-orchestrator/tasks/generate_script.py` builds prompt, calls provider, persists output via `script_service.save_draft(...)`, and completes through task runner with success stage `SCRIPT_REVIEW`.
5. Script retrieval
   - `apps/api/src/shorts_api/routes/creator_script.py` (`GET /runs/{run_id}/script`) returns the active draft content for review stages.
6. Review and approval
   - `apps/api/src/shorts_api/routes/creator_runs_core.py` (`POST /runs/{run_id}/approve-script`) advances run from `SCRIPT_REVIEW` to `VISUAL_PLAN_SETUP`.

## State Transitions in This Slice

- Dispatch start: `IDEA_READY` or `SCRIPT_REVIEW` -> `SCRIPT_GENERATING`
- Worker success: `SCRIPT_GENERATING` -> `SCRIPT_REVIEW`
- Human/agent approval: `SCRIPT_REVIEW` -> `VISUAL_PLAN_SETUP`
- Failure safety: CAS/dispatch failures roll back to prior stage through `cas_dispatch_with_rollback`.
