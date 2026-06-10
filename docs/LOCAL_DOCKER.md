# Local Docker Compose Setup

This guide explains how to run Short Form Studio on a local server using Docker Compose.

## 1. Create environment file

```bash
cp .env.local.example .env
```

Edit `.env` and change `POSTGRES_PASSWORD` and `DATABASE_URL` credentials.

## 2. Start services

```bash
make docker-local-up
```

This starts:

- PostgreSQL
- Redis
- API
- Worker
- Studio Web

## 3. Run database migrations

```bash
make docker-local-migrate
```

## 4. Create API key

```bash
make docker-local-bootstrap
```

Copy the generated API key into `.env`:

```
API_KEY=<generated-key>
```

Then restart the services:

```bash
make docker-local-up
```

## 5. Open Studio

From the local server:

```
http://localhost:5174
```

From another device on the same LAN:

```
http://<server-ip>:5174
```

## 6. Check service status

```bash
make docker-local-status
```

## 7. View logs

```bash
make docker-local-logs
```

## 8. Stop services

```bash
make docker-local-down
```

## Notes

- Only `studio-web` is exposed to the LAN (bound to `0.0.0.0`).
- API, PostgreSQL, and Redis remain bound to `127.0.0.1` for safety.
- If you need to access the API directly from another device, add your server IP to `CORS_ORIGINS` in `.env`.
- For external (internet) access, use a secure reverse proxy or Cloudflare Tunnel.

## Recommended Models for Local Mode

The default model configuration is optimized for local/free execution:

| Category | Default Model | Why |
|----------|--------------|-----|
| TTS | `edge-tts` | No GPU, no API key, free, Korean voices included |
| LLM | `qwen3-4b` (local) or Groq (cloud) | Local Ollama or free Groq tier |
| STT | `whisper-small` (local) or `groq-whisper-large-v3-turbo` | Local or Groq |
| Image | `placeholder` or `hf-flux-schnell` | Placeholder for testing, HF FLUX for real images |

To override defaults, set these in `.env`:

```env
TTS_DEFAULT_MODEL=edge-tts
SCRIPT_DEFAULT_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
SUBTITLE_DEFAULT_MODEL=groq-whisper-large-v3-turbo
```

### Why edge-tts?

Unlike `qwen3-tts` (which requires a GPU-backed TTS container), `edge-tts` runs
without any local GPU or external API key. It provides high-quality Korean voices
suitable for 썰쇼츠 and demo purposes.

Available Korean voices:

| Voice key | Edge TTS voice |
|-----------|---------------|
| `default` | ko-KR-SunHiNeural |
| `female` | ko-KR-SunHiNeural |
| `male` | ko-KR-InJoonNeural |
