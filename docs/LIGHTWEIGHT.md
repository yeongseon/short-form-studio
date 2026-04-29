# Lightweight Mode

Run Short Form Studio **without Docker, PostgreSQL, Redis, or Celery** -- just Python, an API key, and a browser.

## How It Works

The server auto-detects its running mode based on environment variables:

| Variable | Set | Unset |
|---|---|---|
| `DATABASE_URL` | PostgreSQL storage | In-memory storage |
| `REDIS_URL` | Celery async workers | Synchronous in-process execution |

When both are unset, the API server runs entirely in a single process:

```
Browser  -->  FastAPI (uvicorn)  -->  AI Provider (OpenAI, Anthropic, etc.)
                 |
           In-memory storage
           Sync task threads
```

> **Note:** In-memory storage means all data is lost when the server restarts.
> This mode is designed for quick tryouts, demos, and development -- not production.

## Quick Start

### 1. Install Python dependencies

```bash
# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install all packages
pip install -r constraints.txt
pip install -e packages/creator-domain
pip install -e packages/creator-provider
pip install -e packages/creator-service
pip install -e apps/api
```

### 2. Configure API keys

Create a minimal `.env` file (or export environment variables):

```bash
# .env -- lightweight mode (no DATABASE_URL, no REDIS_URL)
OPENAI_API_KEY=sk-your-key-here
CORS_ORIGINS=http://localhost:5173,http://localhost:5174
ARTIFACT_ROOT=./data/artifacts
```

You only need one AI provider key to get started. See the main README for the full list of supported providers.

### 3. Start the API server

```bash
cd apps/api
uvicorn shorts_api.main:app --host 127.0.0.1 --port 8000 --reload
```

You should see:

```
INFO     Starting in lightweight (in-memory) mode
```

### 4. Start the frontend

```bash
cd apps/studio-web
npm ci
npm run dev
```

Open `http://localhost:5174` and start creating.

## Switching to Full Mode

When you're ready for persistent storage and async task processing:

1. Start PostgreSQL and Redis (via Docker Compose or standalone)
2. Set `DATABASE_URL` and `REDIS_URL` in `.env`
3. Run migrations: `alembic upgrade head`
4. Restart the API server

The server will automatically switch to full mode with PostgreSQL storage and Celery workers.

## Limitations

| Feature | Full Mode | Lightweight Mode |
|---|---|---|
| Data persistence | PostgreSQL (durable) | In-memory (lost on restart) |
| Concurrent tasks | Celery workers (parallel) | Thread pool (sequential per task) |
| Task cancellation | Celery revoke | Not supported |
| Multi-instance | Supported | Single process only |
| GPU lock coordination | Redis-based | Not available |

## Troubleshooting

### "Module not found" errors

Make sure all packages are installed in editable mode (`pip install -e`). The lightweight mode imports worker task modules directly, which require all domain/service/provider packages to be available.

### Tasks seem to hang

In lightweight mode, AI tasks run synchronously in background threads. Long-running tasks (image generation, video rendering) may take several minutes. Check the server logs for progress.

### CORS errors in the browser

Ensure `CORS_ORIGINS` includes your frontend URL (default: `http://localhost:5174`).
