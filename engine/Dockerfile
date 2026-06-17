# ─────────────────────────────────────────────────────────────────────────────
# JARVIS TRADER ENGINE — Railway Dockerfile
# Base: Python 3.12 slim (matches pyproject.toml requirement)
# Uses requirements-core.txt — no ta-lib C binary, no vectorbt, no nautilus
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

# ── System deps ──────────────────────────────────────────────────────────────
# build-essential: needed for some Python package C extensions (e.g. psycopg2)
# curl: health check probe
# libpq-dev: PostgreSQL C headers for psycopg2-binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ────────────────────────────────────────────────────────
WORKDIR /app

# ── Python deps (layer-cached) ───────────────────────────────────────────────
# Copy requirements first so Docker cache busts only when deps change
COPY requirements-core.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-core.txt

# ── Application code ─────────────────────────────────────────────────────────
COPY . .

# ── Runtime dirs ─────────────────────────────────────────────────────────────
# Create data dirs that the engine writes to at runtime
RUN mkdir -p \
    data/eod \
    data/morning_briefs \
    data/daily_journals \
    logs

# ── Environment defaults ─────────────────────────────────────────────────────
# These are safe defaults — secrets come from Railway env vars, never baked in
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PORT=8010 \
    LOG_LEVEL=INFO \
    PAPER_TRADING=true \
    LIVE_TRADING_ENABLED=false \
    REQUIRE_HUMAN_APPROVAL=true

# ── Port ─────────────────────────────────────────────────────────────────────
EXPOSE 8010

# ── Health check ─────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8010/health || exit 1

# ── Start command ────────────────────────────────────────────────────────────
# Use PORT env var so Railway can override if needed (Railway injects $PORT)
CMD uvicorn main:app \
    --host 0.0.0.0 \
    --port ${PORT} \
    --workers 1 \
    --loop asyncio \
    --log-level info \
    --no-access-log
