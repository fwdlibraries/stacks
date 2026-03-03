# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# Security: run as non-root
RUN groupadd --gid 1001 stacks && \
    useradd --uid 1001 --gid stacks --shell /bin/bash --create-home stacks

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Dependencies layer ────────────────────────────────────────────────────────
FROM base AS deps

COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# ── Final image ───────────────────────────────────────────────────────────────
FROM deps AS final

COPY --chown=stacks:stacks . .

USER stacks

# Default: API server
# Override CMD in docker-compose for worker: celery -A app.tasks.celery_app worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health/live || exit 1
