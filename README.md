# Short Form Studio

AI-powered short-form video production pipeline -- from idea to rendered video in minutes.

## Overview

Short Form Studio is an open-source platform that automates short-form video creation using AI.
It takes an idea or structured script and produces a complete video with:

- AI-generated scripts (via LLM)
- Visual plans and image generation (via Stable Diffusion or DALL-E)
- Text-to-speech narration (via local Qwen TTS or ElevenLabs/OpenAI)
- Auto-generated subtitles (via Whisper STT)
- Final video rendering (via FFmpeg)

The pipeline is stage-based with human-in-the-loop review at each step.

## Architecture

The project is a monorepo with these main components:

| Component | Path | Description |
|---|---|---|
| **API** | `apps/api/` | FastAPI REST API -- orchestrates the pipeline |
| **Worker** | `apps/worker-orchestrator/` | Celery worker -- runs async AI tasks |
| **Studio Web** | `apps/studio-web/` | React + TypeScript frontend (Vite) |
| **Domain** | `packages/creator-domain/` | Shared domain models (Pydantic) |
| **Service** | `packages/creator-service/` | Business logic and database layer |
| **Providers** | `packages/creator-provider/` | LLM, Image, TTS, STT provider adapters |

## Pipeline Stages

```
IDEA_READY -> SCRIPT_GENERATING -> SCRIPT_REVIEW
  -> VISUAL_PLAN_SETUP -> VISUAL_PLAN_GENERATING -> VISUAL_PLAN_REVIEW
  -> VISUAL_ASSET_GENERATING -> VISUAL_ASSET_REVIEW
  -> AUDIO_GENERATING -> SUBTITLE_GENERATING
  -> RENDER_GENERATING -> FINAL_REVIEW -> PUBLISHED
```

Each `*_REVIEW` stage requires explicit approval before advancing.

## Quick Start

### Prerequisites

- Docker and Docker Compose v2+
- (Optional) NVIDIA GPU + Container Toolkit for local AI models

### 1. Clone and configure

```bash
git clone https://github.com/yeongseon/short-form-studio.git
cd short-form-studio
cp .env.example .env
# Edit .env as needed
```

### 2. Start services

```bash
docker compose up -d
```

### 3. Run database migrations

```bash
docker compose run --rm api alembic upgrade head
```

### 4. Pull the default LLM model

```bash
docker compose exec ollama ollama pull qwen3:4b
```

### 5. Open the Studio

Navigate to `http://localhost:5174` to start creating.

## Supported AI Providers

### Local (GPU required)

| Category | Provider | Model |
|---|---|---|
| LLM | Ollama | qwen3:4b |
| Image | Stable Diffusion | SD 1.5 |
| TTS | Qwen TTS | Local |
| STT | Whisper | large-v3 |

### Remote (API key required)

| Category | Provider | Model | Env Variable |
|---|---|---|---|
| LLM | OpenAI | GPT-4o Mini | `OPENAI_API_KEY` |
| LLM | Anthropic | Claude Sonnet | `ANTHROPIC_API_KEY` |
| LLM | Google | Gemini 2.0 Flash | `GOOGLE_API_KEY` |
| Image | OpenAI | DALL-E 3 | `OPENAI_API_KEY` |
| Image | Stability AI | SD3 Medium | `STABILITY_API_KEY` |
| Image | Google | Imagen 3 | `GOOGLE_API_KEY` |
| TTS | ElevenLabs | Multilingual v2 | `ELEVENLABS_API_KEY` |
| TTS | OpenAI | TTS-1 | `OPENAI_API_KEY` |

## Configuration

See [`.env.example`](.env.example) for all configuration options.

Key settings:

| Variable | Description | Default |
|---|---|---|
| `API_KEY` | API authentication key (leave empty for open access) | _(empty)_ |
| `CORS_ORIGINS` | Allowed CORS origins | `http://localhost:5174` |
| `ARTIFACT_ROOT` | Path for generated artifacts | `./data/artifacts` |
| `OLLAMA_DEFAULT_MODEL` | Default LLM model | `qwen3:4b` |

## Development

### Backend

```bash
# Lint
python3 -m ruff check apps packages

# Run API locally
cd apps/api && uvicorn shorts_api.main:app --reload
```

### Frontend

```bash
cd apps/studio-web
npm ci
npm run dev      # Development server
npm run build    # Production build
npm test         # Run tests
```

### Running Tests

```bash
# Backend tests
python3 -m pytest apps/api/tests/ -x -v

# Frontend tests
cd apps/studio-web && npm test
```

## Service Ports

| Service | Port | Protocol |
|---|---|---|
| API (FastAPI) | 8000 | HTTP |
| Studio Web (Vite) | 5174 | HTTP |
| PostgreSQL | 5432 | TCP |
| Redis | 6379 | TCP |
| Ollama | 11434 | HTTP |
| Stable Diffusion | 7860 | HTTP |
| TTS (Qwen) | 8100 | HTTP |
| STT (Whisper) | 9000 | HTTP |
| Flower (monitoring) | 5555 | HTTP |

## Documentation

- [Usage Guide](docs/USAGE.md) -- Detailed feature walkthrough
- [Deployment Guide](docs/CUTOVER.md) -- Production deployment checklist

## License

This project is open source. See [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome. Please open an issue first to discuss what you would like to change.
