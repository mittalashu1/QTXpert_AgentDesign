# syntax=docker/dockerfile:1

# Playwright's pinned Ubuntu image includes Chromium and its supported system
# dependencies. The previous python:3.12-slim image made Playwright fall back to
# unavailable Ubuntu font packages during Render builds.
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Browsers and system dependencies are provided by the Playwright base image.
RUN chmod -R a+rX /ms-playwright

COPY . .

# Fail the image build before deployment if any application module has invalid Python syntax.
RUN python -m compileall -q app alembic

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/storage/uploads /app/storage/autopilot \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD-SHELL curl -fsS "http://127.0.0.1:\${PORT:-8000}/api/v1/health/live" >/dev/null || exit 1

# A database provider outage must not prevent the HTTP process from starting:
# /api/v1/health can report the degraded dependency and the Autopilot local
# fallback remains inspectable.  Migrations still run on every healthy start;
# a failed attempt is logged and retried by the next deploy/restart.
CMD ["sh", "-c", "if [ \"${RUN_MIGRATIONS:-true}\" = \"true\" ]; then alembic upgrade head || echo 'WARNING: database migrations were deferred; continuing in degraded mode' >&2; fi; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
