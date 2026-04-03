#!/usr/bin/env bash
set -euo pipefail

echo "[1/6] checking iii REST API"
curl -sS http://localhost:3111/api/pool/list >/dev/null && echo "ok"

echo "[2/6] checking repo files"
[[ -f train.py ]] && [[ -f prepare.py ]] && [[ -f program.md ]] && echo "ok"

echo "[3/6] checking uv"
command -v uv >/dev/null && uv --version

echo "[4/6] checking python"
python --version

echo "[5/6] checking data cache"
[[ -d "$HOME/.cache/autoresearch" ]] && echo "cache ok" || echo "warning: ~/.cache/autoresearch missing"

echo "[6/6] checking nvidia-smi"
if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
else
  echo "warning: nvidia-smi not found"
fi
