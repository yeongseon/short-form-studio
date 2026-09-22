# First Short Walkthrough

This is the end-to-end walkthrough for creating your **first Short** with the
bundled sample, from a fresh clone through preview, download, and editing. It
links to [QUICKSTART.md](QUICKSTART.md) for setup rather than duplicating it, and
records an honest time-to-first-Short measurement against the product target.

> **The under-10-minute figure is a _target, not a measured result_.** See
> [Time to First Short measurement](#time-to-first-short-measurement) below for
> the honest recorded validation. This document does not claim the KPI is
> achieved.

## Prerequisites (be honest with yourself here)

| Requirement | Needed for | Notes |
|---|---|---|
| Docker + Docker Compose v2 | Everything | The whole stack runs in containers. |
| `OPENAI_API_KEY` | Script / image / TTS on the CPU path | Remote provider; the CPU path cannot generate without it. |
| `GROQ_API_KEY` | Subtitles (STT) on the CPU path | Remote provider for Whisper-class STT. |
| NVIDIA GPU + `--profile gpu` | Local model generation | **Optional.** Local model images are GPU-gated and not shipped in this repo. |

**Generation cannot proceed without either remote provider keys or a working
GPU/local-model setup.** With neither configured, you can still install, start
the stack, open the Studio, and reach setup readiness — but the pipeline stops at
the first generate step. That limitation is by design, not a bug.

## 1. Install and set up

Follow the canonical steps in [QUICKSTART.md](QUICKSTART.md). In short:

```bash
git clone https://github.com/yeongseon/short-form-studio.git
cd short-form-studio
cp .env.example .env
# Edit .env: set OPENAI_API_KEY and GROQ_API_KEY for the CPU path
docker compose up -d
docker compose run --rm api alembic upgrade head
docker compose run --rm api python scripts/create_api_key.py \
  --email local@example.com --workspace local --name local-dev
```

Then open the Studio at `http://127.0.0.1:5174`.

## 2. Confirm setup readiness

Check that prerequisites are configured before you try to generate. The onboarding
surface reports first-run vs returning state, the duration presets, the human
review gates, and the next action:

- `GET /api/creator/workspaces/{workspace_id}/onboarding`

If a required provider is missing, the onboarding `next_action` guides you to set
the env var and restart, mirroring the first-run Setup Wizard.

## 3. Create a sample-backed first Short (optional demo flow)

The one-click demo seeds a Short from the reproducible sample project. First
review what it will do — estimated costs, required provider configuration, and the
approvals it will _not_ bypass:

- `GET /api/creator/projects/{project_id}/demo-short/plan`

Then seed the run. This creates a **new, workspace-owned "Demo Short" project**
with a real sample-backed timeline, plus a normal run at the `IDEA_READY` stage;
it does **not** mutate your existing project and does **not** auto-advance or
auto-approve anything:

- `POST /api/creator/workspaces/{workspace_id}/demo-short/runs`

The Short then moves through the normal pipeline, which has **four human review
gates that are surfaced, never bypassed**: `SCRIPT` review, `VISUAL_PLAN` review,
`VISUAL_ASSET` review, and `FINAL` review. You approve each one explicitly.

## 4. (Optional) Upload your own media

The sample-backed path needs no uploads, but you can incorporate your own images,
video, or audio:

- `POST /api/creator/workspaces/{workspace_id}/assets` (image)
- `POST /api/creator/workspaces/{workspace_id}/assets/audio`
- `POST /api/creator/workspaces/{workspace_id}/assets/videos`

## 5. Generate, review, preview, download, and Edit

Drive the pipeline through its stages (each generate step requires the relevant
provider prerequisite):

- Generate scene images: `POST /api/creator/runs/{run_id}/visual-plan/scenes/{scene_id}/generate-image`
- Generate narration: `POST /api/creator/runs/{run_id}/generate-audio`
- Generate subtitles: `POST /api/creator/runs/{run_id}/generate-subtitles`
- Render the video: `POST /api/creator/runs/{run_id}/render`
- **Preview** the render: `GET /api/creator/runs/{run_id}/preview`
- Preview the editable Timeline: `GET /api/creator/projects/{project_id}/timeline/preview`
- **Download** the finished Short: `GET /api/creator/runs/{run_id}/artifacts/{artifact_id}/download`
- **Edit** the draft: load and save the Timeline via
  `GET /api/creator/projects/{project_id}/timeline` and
  `PUT /api/creator/projects/{project_id}/timeline`, plus scene-level edits in the
  Studio's Scene View.

### Local-only preview and download

Previews and downloads are served on the **loopback interface (`127.0.0.1`) only**.
The stack is never bound to `0.0.0.0` by default, and artifacts are **not exposed
externally automatically**. If you need to share an artifact beyond the local
machine, do so explicitly and deliberately — see [SECURITY.md](SECURITY.md).

### When something fails

Errors across creation and editing are mapped to actionable recovery steps
without leaking secrets or internal paths. A failed run/task exposes a safe
failure summary (category, whether it is retryable, and recovery steps), so you
can tell a transient provider hiccup (retry) from a missing prerequisite (fix and
re-run) from a genuine conflict (refresh and reapply). See
[USAGE.md](USAGE.md) for the review-and-recovery flow.

## Time to First Short measurement

**Definition.** _Start_ = the moment you begin a fresh clone/setup. _End_ = the
first previewed or downloaded Short. The product target is **under 10 minutes,
including setup** — a _target, not a measured result_, and this document makes no
claim that the target is achieved.

**How to measure it yourself.** Note the wall-clock time when you run
`git clone`, then note it again when `GET /api/creator/runs/{run_id}/preview`
first returns your rendered Short (or when the download completes). Record the
environment (CPU remote-provider path or GPU path), the elapsed time, and any
prerequisites or waiting points (image pulls, container health, provider
latency). Timing is environment-dependent and is not asserted in CI.

### Recorded validation runs

| Date | Environment | Start | End | Elapsed | Result | Notes |
|---|---|---|---:|---:|---|---|
| 2026-09-21 | Local, CPU remote-provider path, **no provider keys configured** | Fresh clone / setup start | Setup readiness reached; generation blocked | ~0m to block | **Not a completed first Short** | No `OPENAI_API_KEY` / `GROQ_API_KEY` configured and local GPU model images not shipped, so the first generate step could not run. **KPI not measured / not achieved.** The install→start→open→readiness path completed; the generate→preview→download path is blocked pending provider prerequisites. |

The recorded run above is a **prerequisite-blocked attempt**: it honestly reflects
that no successful end-to-end time-to-first-Short has been measured in this
environment, and it does **not** claim the KPI is achieved. A completed timed run
requires configured provider keys (CPU path) or a GPU/local-model setup; record
it in the table above when you run it.
