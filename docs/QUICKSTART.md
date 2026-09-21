# Quick Start — Your First Short (CPU / remote providers)

This is the fastest reproducible path from a clean machine to your first
short-form video, using **remote AI providers** and **no GPU**. The local GPU
services are an optional path documented at the end.

> The project [README](../README.md) also has a Quick Start overview; **this file
> is the reproducible, first-short-focused path** with failure recovery.

## 1. Prerequisites

- Docker and Docker Compose v2+ (`docker compose version`).
- No GPU required. The CPU path uses remote providers for the LLM, image, TTS, and
  speech-to-text (subtitle) stages, because the local model services are gated
  behind the optional `gpu` profile.

## 2. Clone and configure

```bash
git clone https://github.com/yeongseon/short-form-studio.git
cd short-form-studio
cp .env.example .env
```

Edit `.env`:

- **Change the database password** (never ship the placeholder):
  - `POSTGRES_PASSWORD=<a-strong-password>`
  - update the same password inside `DATABASE_URL`.
- **Set a strong admin key**: `ADMIN_API_KEY=<a-strong-random-string>` (min 16
  chars; required in production mode).
- **Set the remote provider keys** for a full CPU pipeline:
  - `OPENAI_API_KEY=<your-openai-api-key>` — powers the script (LLM, `gpt-4o-mini`),
    images (`dall-e-3`), and narration (TTS, `openai-tts-1`).
  - `GROQ_API_KEY=<your-groq-api-key>` — powers remote speech-to-text for
    auto-subtitles (`groq-whisper-large-v3-turbo`). The default `whisper-small`
    STT model is local/GPU, so a remote STT key is what keeps the CPU path
    complete. If you do not need burned-in subtitles yet, you can defer this key
    and set `burn_subtitles` off in your render settings.

> **Security defaults are already safe.** Every published port binds to
> `127.0.0.1` only (Postgres, Redis, the API on `127.0.0.1:8000`, and the studio
> UI on `127.0.0.1:5174`), so nothing is exposed on your LAN. Do not change these
> to `0.0.0.0`. Keep `ENVIRONMENT=development` for local use; production mode
> rejects the default password and enforces `CORS_ORIGINS`.

## 3. Start the CPU core

```bash
docker compose up -d
```

This starts only the CPU core — Postgres, Redis, the API, the worker, the beat
scheduler, and the studio web UI. The GPU model services (Ollama, Stable
Diffusion, local TTS/STT) stay stopped because they are behind the `gpu` profile.

## 4. Run database migrations

```bash
docker compose run --rm api alembic upgrade head
```

Run this before first use; the API needs the schema in place.

## 5. Bootstrap an API key (first time only)

```bash
docker compose run --rm api python scripts/create_api_key.py \
  --email local@example.com \
  --workspace local \
  --name local-dev
```

This creates a user, a workspace, and an API key for local development; the key is
printed to stdout. Keep it — the studio UI and API use it to authenticate.

## 6. Open the studio and make your first Short

Navigate to <http://127.0.0.1:5174>. From there:

1. Start a new project from an idea or script.
2. Approve each stage (script → visual plan → images → audio → subtitles → render).
   With the remote keys set, every stage runs without a GPU.
3. Review the final render and publish.

## Optional: local GPU path

If you have an NVIDIA GPU with the Container Toolkit and want fully local
inference (no remote API keys), start the GPU services alongside the core:

```bash
docker compose --profile gpu up -d
# then pull the default local LLM (first time only):
docker compose exec ollama ollama pull qwen3:4b
```

The `gpu` profile adds Ollama, Stable Diffusion, and the local TTS/STT services.
See [Local Docker setup](LOCAL_DOCKER.md) for LAN access and
[Security model](SECURITY.md) for trust boundaries.

## Verify the setup (smoke check)

Before (or instead of) bringing the stack up, run the static smoke check. It
validates the compose config, confirms the CPU core is not GPU-gated, confirms
every published port is loopback-only, and confirms the referenced env vars and
bootstrap/migration entrypoints exist:

```bash
bash scripts/quickstart_smoke.sh
```

## Failure recovery / troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| A stage errors with "provider not configured" / auth error | The relevant provider key is blank in `.env` | Set `OPENAI_API_KEY` (script/image/TTS) and `GROQ_API_KEY` (subtitles), then `docker compose up -d` to reload |
| API errors about missing tables / relations | Migrations not run | `docker compose run --rm api alembic upgrade head` |
| API/UI won't start; "default password" or CORS error at boot | `ENVIRONMENT=production` with the placeholder password or missing `CORS_ORIGINS` | Keep `ENVIRONMENT=development` locally, or set a real `POSTGRES_PASSWORD`, `ADMIN_API_KEY`, and `CORS_ORIGINS` |
| Port already in use on `127.0.0.1:5174` / `:8000` | Another process holds the port | Stop it, or remap the host port in `docker-compose.yml` (keep the `127.0.0.1:` prefix) |
| Auto-subtitles fail but the rest renders | No remote STT key and local Whisper is GPU-only | Set `GROQ_API_KEY`, or disable burned-in subtitles for now |
| GPU services fail to start | No GPU / missing NVIDIA Container Toolkit, or the local images are not built | Use the CPU/remote path above; the `gpu` profile is optional |

To reset a broken local stack completely:

```bash
docker compose down -v   # WARNING: -v drops the database volume
```
