# --- build stage ---
FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir --upgrade pip
COPY packages ./packages
COPY apps/worker-orchestrator/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    ./packages/creator-domain \
    ./packages/creator-service \
    ./packages/creator-provider

# --- runtime stage ---
FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder /install /usr/local
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY apps/worker-orchestrator/tasks ./tasks
COPY apps/worker-orchestrator/celery_app.py ./celery_app.py
CMD ["celery", "-A", "celery_app.celery_app", "worker", "--loglevel=info"]

# --- dev stage ---
FROM runtime AS dev
RUN pip install --no-cache-dir watchfiles
CMD ["sh", "-c", "watchfiles 'celery -A celery_app.celery_app worker --loglevel=info --pool=solo' /app"]
