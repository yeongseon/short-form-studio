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
   | `CORS_ORIGINS` | Yes | Default: `http://localhost:5174` |
   | `ARTIFACT_ROOT` | Yes | Default: `./data/artifacts` |
   | `OLLAMA_BASE_URL` | Yes | Default: `http://ollama:11434` |
   | `OLLAMA_DEFAULT_MODEL` | Yes | Default: `qwen3:4b` |
   | `STABLE_DIFFUSION_BASE_URL` | Yes | Default: `http://stable-diffusion:7860` |
| `TTS_QWEN3_BASE_URL` | Yes | Default: `http://tts-qwen3:8100` |
| `STT_WHISPER_BASE_URL` | Yes | Default: `http://stt-whisper:8200` |
   | `GPU_LOCK_KEY` | Yes | Default: `gpu:lock` |
   | `GPU_LOCK_TIMEOUT_SECONDS` | Yes | Default: `600` |
| `OPENAI_API_KEY` | No | External LLM/Image/TTS provider |
| `ANTHROPIC_API_KEY` | No | External LLM provider |
| `GOOGLE_API_KEY` | No | External LLM/Image provider |
| `STABILITY_API_KEY` | No | External image provider |
| `ELEVENLABS_API_KEY` | No | External TTS fallback |

3. **Ensure AI model images exist** (pre-built locally; not shipped in this repo)

   ```bash
   docker images | grep short-form-studio
   # Expected:
   #   short-form-studio-stable-diffusion
#   short-form-studio-tts-qwen3
   #   short-form-studio-stt-whisper
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

**Migrations** are applied automatically by `alembic upgrade head`. To inspect current state:

```bash
docker compose run --rm api alembic history
docker compose run --rm api alembic current
docker compose run --rm api alembic heads
```

### Step 4: (Optional) Pull Ollama Model

Only needed when using the `gpu` profile for local AI inference.

```bash
docker compose --profile gpu up -d ollama
# Wait for health check to pass, then:
docker compose exec ollama ollama pull qwen3:4b
```

### Step 5: (Optional) Start GPU AI Services

GPU-based AI services are gated behind the `gpu` Docker Compose profile.
Skip this step if you only use remote API providers.

```bash
docker compose --profile gpu up -d
```

> **Note:** Requires NVIDIA GPU + Container Toolkit. Only one model runs inference at a time (GPU lock via Redis).

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
curl -f http://localhost:8000/healthz

# Studio Web
curl -sf http://localhost:5174/ | head -1

# Flower (if monitoring profile enabled)
curl -sf http://localhost:5555/

# Ollama (GPU profile only)
curl -f http://localhost:11434/api/tags

# Stable Diffusion (GPU profile only)
curl -f http://localhost:7860/sdapi/v1/options
```

### Route Smoke Tests (Browser)

| Route | Expected |
|---|---|
| `http://localhost:5174/` | Redirects to `/create` |
| `http://localhost:5174/create` | Create New Project form |
| `http://localhost:5174/runs` | Project list (empty initially) |
| `http://localhost:5174/ops` | Operations dashboard |
| `http://localhost:5174/settings` | Provider API key status page |
| `http://localhost:5174/nonexistent` | Redirects to `/create` |

### End-to-End Smoke Test

1. Navigate to `http://localhost:5174/create`
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
  /settings            → SettingsPage (provider API key status)

Redirects:
  /                    → /create
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

| Service | Bind Address | Port | Protocol | Notes |
|---|---|---|---|---|
| API (FastAPI) | 127.0.0.1 | 8000 | HTTP | Internal only |
| Studio Web (nginx) | 127.0.0.1 | 5174→8080 | HTTP | Local only; put behind authenticated reverse proxy for public access |
| PostgreSQL | 127.0.0.1 | 5432 | TCP | Internal only |
| Redis | 127.0.0.1 | 6379 | TCP | Internal only |
| Ollama | 127.0.0.1 | 11434 | HTTP | GPU profile only |
| Stable Diffusion | 127.0.0.1 | 7860 | HTTP | GPU profile only |
| TTS (Qwen) | 127.0.0.1 | 8100 | HTTP | GPU profile only |
| STT (Whisper) | 127.0.0.1 | 9000 | HTTP | GPU profile only |
| Flower | 127.0.0.1 | 5555 | HTTP | Monitoring profile |

> **Security note:** All services bind to `127.0.0.1` by default to prevent
> accidental exposure. For public access, place `studio-web` behind an
> authenticated reverse proxy — do **not** change its bind address to `0.0.0.0`.
---

## GPU Constraints

- **Single GPU** (GTX 1660 SUPER, 6 GB VRAM)
- **One model at a time** — GPU lock via Redis key `gpu:lock`
- Lock timeout: 600s (configurable via `GPU_LOCK_TIMEOUT_SECONDS`)
- Default LLM: `qwen3:4b` (fits in 6 GB VRAM)
- Rendering: **CPU-only** (FFmpeg, no GPU required)

---

## Artifact Storage

- Development: local filesystem at `data/artifacts/{run_id}/`
- Production: supports S3/Azure Blob/GCS-compatible object storage
- Artifact access goes through `artifact_id`-based download routes
- Path-based artifact endpoints are deprecated and blocked in production/staging
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
| GPU lock stuck | Previous task crashed | Check lock ownership: `docker compose exec redis redis-cli GET gpu:lock`. If orphaned (owner dead), delete with `redis-cli DEL gpu:lock`. Lock uses token-based ownership and auto-renewal; avoid deleting active locks. |
| Ollama model not found | Model not pulled | `docker compose exec ollama ollama pull qwen3:4b` |
| CORS errors in browser | Wrong `CORS_ORIGINS` | Set to `http://localhost:5174` |
| Worker not processing | Celery not connected to Redis | Check `REDIS_URL` in `.env` |
| Studio Web blank page | API not running | Check `docker compose ps api` |
| AI service unhealthy | GPU not available | Check `nvidia-smi`, verify NVIDIA Container Toolkit |
