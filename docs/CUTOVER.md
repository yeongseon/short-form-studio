# Cutover Checklist & Deployment Notes

Operator-facing guide for deploying and verifying the short-form-studio system.

---

## Prerequisites

| Component | Requirement |
|---|---|
| Docker & Docker Compose | v2.x+ |
| NVIDIA GPU | GTX 1660 SUPER 6 GB VRAM (or compatible) |
| NVIDIA Container Toolkit | `nvidia-ctk` installed, Docker runtime configured |
| CUDA | 12.2+ |
| RAM | 32 GB recommended |
| Disk | 50 GB+ free (models + artifacts) |

## Environment Setup

1. **Copy environment file**

   ```bash
   cp .env.example .env
   ```

2. **Review and set variables in `.env`**

   | Variable | Required | Notes |
   |---|---|---|
   | `POSTGRES_DB` | Yes | Database name |
   | `POSTGRES_USER` | Yes | Database user |
   | `POSTGRES_PASSWORD` | Yes | **Change from default** |
   | `REDIS_URL` | Yes | Default: `redis://redis:6379/0` |
   | `API_HOST` / `API_PORT` | Yes | Default: `0.0.0.0:8000` |
   | `CORS_ALLOWED_ORIGINS` | Yes | Default: `http://localhost:5173` (internal), exposed as `5174` on host |
   | `ARTIFACT_ROOT` | Yes | Default: `./data/artifacts` |
   | `OLLAMA_BASE_URL` | Yes | Default: `http://ollama:11434` |
   | `OLLAMA_DEFAULT_MODEL` | Yes | Default: `qwen3:4b` |
   | `STABLE_DIFFUSION_BASE_URL` | Yes | Default: `http://stable-diffusion:7860` |
| `TTS_QWEN3_BASE_URL` | Yes | Default: `http://tts-qwen3:8100` |
   | `STT_WHISPER_BASE_URL` | Yes | Default: `http://stt-whisper:9000` |
   | `GPU_LOCK_KEY` | Yes | Default: `gpu:lock` |
   | `GPU_LOCK_TIMEOUT_SECONDS` | Yes | Default: `600` |
   | `OPENAI_API_KEY` | No | External LLM fallback |
   | `REPLICATE_API_TOKEN` | No | External image generation fallback |
   | `AZURE_SPEECH_KEY` | No | External TTS fallback |
   | `ELEVENLABS_API_KEY` | No | External TTS fallback |

3. **Ensure AI model images exist** (pre-built from shorts-automation project)

   ```bash
   docker images | grep shorts-automation
   # Expected:
   #   shorts-automation-stable-diffusion
#   shorts-automation-tts-qwen3
   #   shorts-automation-stt-whisper
   ```

---

## Deployment Steps

### Step 1: Pull / Build Images

```bash
# Pull standard images
docker compose pull postgres redis ollama

# Build application images
docker compose build api worker studio-web
```

### Step 2: Start Infrastructure

```bash
docker compose up -d postgres redis
# Wait for health checks
docker compose ps  # Both should be "healthy"
```

### Step 3: Run Database Migrations

```bash
docker compose run --rm api alembic upgrade head
```

**Migration order** (applied automatically by `upgrade head`):

| # | Migration | Creates |
|---|---|---|
| 001 | `create_creator_projects` | `creator_projects` table |
| 002 | `create_creator_runs` | `creator_runs` table |
| 003 | `create_creator_stage_reviews` | `creator_stage_reviews` table |
| 004 | `create_creator_scene_assets` | `creator_scene_assets` table |
| 005 | `expand_artifact_typing_and_indexes` | `creator_artifacts` table + indexes |
| 006 | `create_creator_script_drafts` | `creator_script_drafts` table |
| 007 | `create_creator_visual_plans` | `creator_visual_plans` table |
| 008 | `add_paragraph_artifact_index` | Paragraph artifact index |
| 009 | `add_active_task_id` | `active_task_id` column on runs |
| 010 | `widen_active_task_id` | Widens `active_task_id` column type |
| 011 | `add_pasted_json_source_type` | `pasted_json` source type + `json_script` column |

### Step 4: Pull Ollama Model

```bash
docker compose up -d ollama
# Wait for health check to pass, then:
docker compose exec ollama ollama pull qwen3:4b
```

### Step 5: Start AI Services

```bash
docker compose up -d stable-diffusion tts-qwen3 stt-whisper
```

> **Note:** AI services require the NVIDIA GPU. Only one model runs inference at a time (GPU lock via Redis).

### Step 6: Start Application

```bash
docker compose up -d api worker studio-web
```

### Step 7: (Optional) Start Monitoring

```bash
docker compose --profile monitoring up -d flower
```

---

## Post-Deployment Verification

### Health Checks

```bash
# API health
curl -f http://localhost:8000/api/health

# Studio Web
curl -sf http://localhost:5173/ | head -1

# Flower (if monitoring profile enabled)
curl -sf http://localhost:5555/

# Ollama
curl -f http://localhost:11434/api/tags

# Stable Diffusion
curl -f http://localhost:7860/sdapi/v1/options
```

### Route Smoke Tests (Browser)

| Route | Expected |
|---|---|
| `http://localhost:5173/` | Redirects to `/create` |
| `http://localhost:5173/create` | Create New Project form |
| `http://localhost:5173/runs` | Project list (empty initially) |
| `http://localhost:5173/ops` | Operations dashboard |
| `http://localhost:5173/ops/library` | Asset Library page |
| `http://localhost:5173/library` | Redirects to `/ops/library` |
| `http://localhost:5173/nonexistent` | Redirects to `/create` |

### End-to-End Smoke Test

1. Navigate to `http://localhost:5173/create`
2. Enter an idea (e.g., "Test video about coding")
3. Submit → Project created, redirects to `/projects/:id`
4. Verify stage progression: `IDEA_READY` shown in Project page

### Frontend Test Suite

```bash
cd apps/studio-web
npx vitest run --reporter=verbose
```

Expected: All tests pass (RouteSmoke 13, AppShell 17, OpsPage 8, + per-page suites).

### Backend Test Suite

```bash
python3 -m pytest apps/api/tests/ -x -v
```

---

## Route Map

```
Creator Flow:
  /create              → CreatePage (new project form)
  /projects/:projectId → ProjectPage (stage-by-stage workflow)
  /review/:runId       → ReviewPage (final review before publish)
  /runs                → RunsPage (project list)

Ops Flow:
  /ops                 → OpsPage (monitoring, tools, system info)
  /ops/library         → LibraryPage (asset browser)

Redirects:
  /                    → /create
  /library             → /ops/library (legacy redirect)
  /*                   → /create (catch-all)
```

---

## Stage Pipeline

```
IDEA_READY → SCRIPT_GENERATING → SCRIPT_REVIEW →
VISUAL_PLAN_GENERATING → VISUAL_PLAN_REVIEW →
VISUAL_ASSET_GENERATING → VISUAL_ASSET_REVIEW →
AUDIO_GENERATING → SUBTITLE_GENERATING →
RENDER_GENERATING → FINAL_REVIEW → PUBLISHED
                                  ↘ FAILED
```

Each `*_REVIEW` stage requires explicit approval before advancing.

---

## Service Ports

| Service | Port | Protocol |
|---|---|---|
| API (FastAPI) | 8000 | HTTP |
| Studio Web (Vite) | 5173 | HTTP |
| PostgreSQL | 5432 | TCP |
| Redis | 6379 | TCP |
| Ollama | 11434 | HTTP |
| Stable Diffusion | 7860 | HTTP |
| TTS (Piper) | 5000 | HTTP |
| STT (Whisper) | 9000 | HTTP |
| Flower | 5555 | HTTP |

---

## GPU Constraints

- **Single GPU** (GTX 1660 SUPER, 6 GB VRAM)
- **One model at a time** — GPU lock via Redis key `gpu:lock`
- Lock timeout: 600s (configurable via `GPU_LOCK_TIMEOUT_SECONDS`)
- Default LLM: `qwen3:4b` (fits in 6 GB VRAM)
- Rendering: **CPU-only** (FFmpeg, no GPU required)

---

## Artifact Storage

- Path: `data/artifacts/{project_id}/{run_id}/`
- Stored locally on host filesystem
- Mounted into worker container via Docker volume
- Types: `idea`, `script`, `visual_plan`, `visual_asset`, `audio`, `subtitle`, `video`, `render_manifest`

---

## Rollback

### Application Rollback

```bash
# Stop services
docker compose down

# Checkout previous version
git checkout <previous-tag-or-commit>

# Rebuild and restart
docker compose build api worker studio-web
docker compose up -d
```

### Database Rollback

```bash
# Downgrade one migration
docker compose run --rm api alembic downgrade -1

# Or downgrade to specific revision
docker compose run --rm api alembic downgrade <revision>
```

> **Warning:** Downgrading drops tables/columns. Back up data first if artifacts exist.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| API fails to start | Missing env vars | Check `.env` matches `.env.example` |
| Migration fails | DB not ready | Wait for `postgres` health check |
| GPU lock stuck | Previous task crashed | `docker compose exec redis redis-cli DEL gpu:lock` |
| Ollama model not found | Model not pulled | `docker compose exec ollama ollama pull qwen3:4b` |
| CORS errors in browser | Wrong `CORS_ALLOWED_ORIGINS` | Set to `http://localhost:5173` |
| Worker not processing | Celery not connected to Redis | Check `REDIS_URL` in `.env` |
| Studio Web blank page | API not running | Check `docker compose ps api` |
| AI service unhealthy | GPU not available | Check `nvidia-smi`, verify NVIDIA Container Toolkit |
