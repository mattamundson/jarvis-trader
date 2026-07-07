#!/usr/bin/env bash
# Devcontainer post-create bootstrap for jarvis-trader.
# Runs once after the container is built. Idempotent — safe to re-run.
set -euo pipefail

echo "[jarvis-trader devcontainer] post-create starting..."

# --- Playwright system deps (used by several engine scrapers) -------------
# Install minimal deps; skip browser downloads unless requested.
if command -v playwright >/dev/null 2>&1; then
  echo "[post-create] playwright already present"
else
  sudo apt-get update -y
  sudo apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2
  sudo rm -rf /var/lib/apt/lists/*
fi

# --- Python venv for engine/ ----------------------------------------------
if [[ ! -x "engine/.venv/bin/python" ]]; then
  echo "[post-create] creating engine/.venv"
  python3.12 -m venv engine/.venv
fi

# shellcheck disable=SC1091
source engine/.venv/bin/activate
python -m pip install --upgrade pip wheel setuptools

if [[ -f engine/requirements.txt ]]; then
  echo "[post-create] installing engine/requirements.txt"
  pip install -r engine/requirements.txt
elif [[ -f engine/requirements-core.txt ]]; then
  echo "[post-create] installing engine/requirements-core.txt (fallback)"
  pip install -r engine/requirements-core.txt
fi

deactivate

# --- pnpm for dashboard/ --------------------------------------------------
if ! command -v pnpm >/dev/null 2>&1; then
  echo "[post-create] installing pnpm"
  npm install -g pnpm
fi

if [[ -f dashboard/package.json ]]; then
  echo "[post-create] installing dashboard deps"
  (cd dashboard && pnpm install --frozen-lockfile || pnpm install)
fi

echo "[jarvis-trader devcontainer] post-create done."
echo "  engine API    -> http://localhost:8010  (forwarded)"
echo "  dashboard     -> http://localhost:3010  (forwarded)"
echo "  All other ports are ignored by default."
