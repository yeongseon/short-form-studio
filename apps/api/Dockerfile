# --- build stage ---
FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir --upgrade pip
COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- runtime stage ---
FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder /install /usr/local
COPY apps/api/src ./src
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations
COPY packages ./packages
ENV PYTHONPATH=/app/src:/app
EXPOSE 8000
CMD ["uvicorn", "shorts_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- dev stage ---
FROM runtime AS dev
RUN pip install --no-cache-dir watchfiles
CMD ["uvicorn", "shorts_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
