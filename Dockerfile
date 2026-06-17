# ─────────────────────────────────────────────────────────────────────────────
# JARVIS TRADER ENGINE — Railway Dockerfile (repo root)
# Build context is the repo root; engine/ subdir is the application.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only requirements first for layer caching
COPY engine/requirements-core.txt ./requirements-core.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-core.txt

# Copy engine source
COPY engine/ .

# Runtime dirs
RUN mkdir -p data/eod data/morning_briefs data/daily_journals logs

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PORT=8010 \
    LOG_LEVEL=INFO \
    PAPER_TRADING=true \
    LIVE_TRADING_ENABLED=false \
    REQUIRE_HUMAN_APPROVAL=true

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8010/health || exit 1

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1 --loop asyncio --log-level info --no-access-log
