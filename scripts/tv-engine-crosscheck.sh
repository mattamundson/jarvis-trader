#!/usr/bin/env bash
# Read-only TradingView <-> engine cross-check for the /jarvis-tv-chart command.
#
# Loads the engine API key and issues EXACTLY two authenticated GETs — the price
# snapshot and the Hidden-Pivots level ladder — for the given symbol/timeframe.
# No other endpoint is contacted and nothing is mutated: this is the numeric
# drift check only. Keeping it in a fixed script (rather than inline curl in the
# slash command) means the command's allowlist can pin a single, side-effect-free
# entry point instead of raw `curl`, which could otherwise reach side-effecting
# GETs like /hidden-pivots/scan (fires WhatsApp) or POST routes.
#
# Usage: bash scripts/tv-engine-crosscheck.sh <SYMBOL> <ENGINE_TF>
#   SYMBOL     jarvis symbol, e.g. MES or MGC
#   ENGINE_TF  engine alias, e.g. 5m | 15m | 1h | 4h | 1d  (NOT a TV resolution)
set -euo pipefail

SYMBOL="${1:?usage: tv-engine-crosscheck.sh <SYMBOL> <ENGINE_TF>}"
ENGINE_TF="${2:?usage: tv-engine-crosscheck.sh <SYMBOL> <ENGINE_TF>}"
BASE="${JARVIS_ENGINE_BASE:-http://localhost:8010}"

# Prefer an exported key; else read API_KEY from engine/.env (AGENTS.md: the local
# dev key lives there as API_KEY=...). Strip optional surrounding quotes.
if [ -n "${JARVIS_API_KEY:-}" ]; then
  API_KEY="$JARVIS_API_KEY"
else
  API_KEY="$(grep -E '^API_KEY=' engine/.env 2>/dev/null | head -1 | cut -d= -f2-)"
  API_KEY="${API_KEY%\"}"; API_KEY="${API_KEY#\"}"
fi

if [ -z "${API_KEY:-}" ]; then
  echo "no engine API key (JARVIS_API_KEY unset and engine/.env has none) — skipping cross-check" >&2
  exit 3
fi

echo "# /prices/snapshot?symbols=$SYMBOL"
curl -s -X GET -H "X-API-Key: $API_KEY" "$BASE/prices/snapshot?symbols=$SYMBOL"
echo
echo "# /hidden-pivots/levels/$SYMBOL?timeframe=$ENGINE_TF"
curl -s -X GET -H "X-API-Key: $API_KEY" "$BASE/hidden-pivots/levels/$SYMBOL?timeframe=$ENGINE_TF"
echo
