# --- build stage ---
FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir --upgrade pip
COPY packages ./packages
COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    ./packages/creator-domain \
    ./packages/creator-service \
    ./packages/creator-provider

# --- runtime stage ---
FROM python:3.12-slim AS runtime
RUN groupadd --gid 1000 appuser && useradd --uid 1000 --gid appuser --create-home appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=appuser:appuser apps/api/src ./src
COPY --chown=appuser:appuser apps/api/alembic.ini ./alembic.ini
COPY --chown=appuser:appuser apps/api/migrations ./migrations
ENV PYTHONPATH=/app/src
USER appuser
EXPOSE 8000
CMD ["uvicorn", "shorts_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- dev stage ---
FROM runtime AS dev
RUN pip install --no-cache-dir watchfiles
CMD ["uvicorn", "shorts_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
