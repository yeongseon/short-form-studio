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
