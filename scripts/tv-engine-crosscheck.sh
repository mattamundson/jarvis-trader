#!/usr/bin/env bash
# Read-only TradingView <-> engine cross-check for the /jarvis-tv-chart command.
#
# Loads the engine API key and issues EXACTLY two authenticated GETs — the price
# snapshot and the Hidden-Pivots level ladder — for the given symbol/timeframe.
# No other endpoint is contacted and nothing is mutated: this is the numeric
# drift check only. Keeping it in a fixed script (rather than inline curl in the
# slash command) lets the command's allowlist pin a single, side-effect-free
# entry point instead of raw `curl`.
#
# Usage: bash scripts/tv-engine-crosscheck.sh <SYMBOL> <ENGINE_TF>
#   SYMBOL     jarvis symbol: MES | MGC | MNQ | MCL
#   ENGINE_TF  engine alias:  1m | 5m | 15m | 1h | 4h | 1d  (NOT a TV resolution)
#              OR `none` for PRICE-ONLY mode — the price snapshot is
#              timeframe-independent, so a chart TF with no exact engine alias
#              (e.g. 30m, weekly) passes `none` to check price and skip levels.
set -euo pipefail

SYMBOL="${1:?usage: tv-engine-crosscheck.sh <SYMBOL> <ENGINE_TF|none>}"
ENGINE_TF="${2:?usage: tv-engine-crosscheck.sh <SYMBOL> <ENGINE_TF|none>}"
BASE="${JARVIS_ENGINE_BASE:-http://localhost:8010}"

# Validate BOTH args against fixed allowlists BEFORE building any URL. Without
# this, a non-canonical symbol like `../scan` would be normalized by curl into
# /hidden-pivots/scan — a GET that fires WhatsApp alerts via _notify_hp_signal
# (hidden_pivots_router.py:194,232-235) — defeating the read-only contract.
SYMBOL="$(printf '%s' "$SYMBOL" | tr '[:lower:]' '[:upper:]')"
case "$SYMBOL" in
  MES|MGC|MNQ|MCL) ;;
  *) echo "refusing non-canonical symbol '$SYMBOL' (allowed: MES MGC MNQ MCL)" >&2; exit 2 ;;
esac
case "$ENGINE_TF" in
  1m|5m|15m|1h|4h|1d|none) ;;
  *) echo "refusing unsupported engine timeframe '$ENGINE_TF' (allowed: 1m 5m 15m 1h 4h 1d | none)" >&2; exit 2 ;;
esac

# Prefer an exported key; else read API_KEY from engine/.env (AGENTS.md: the local
# dev key lives there as API_KEY=...). Strip optional surrounding quotes.
if [ -n "${JARVIS_API_KEY:-}" ]; then
  API_KEY="$JARVIS_API_KEY"
else
  # `|| true` so a missing engine/.env or no API_KEY line yields an empty string
  # and the exit-3 skip below fires, instead of set -e aborting on grep's non-zero.
  API_KEY="$(grep -E '^API_KEY=' engine/.env 2>/dev/null | head -1 | cut -d= -f2- || true)"
fi
# ORDER MATTERS: strip the trailing CR FIRST, then surrounding quotes. On Windows
# (the intended env) engine/.env is often CRLF, so a quoted value arrives as
# API_KEY="secret"\r -- the \r is the last char, so a quote-strip-first would leave
# the closing quote in place (curl sends `secret"` -> 401), and an unquoted CRLF
# value would send `secret\r` -> a malformed header Uvicorn 400s. Doing CR then
# quotes handles both.
API_KEY="${API_KEY%$'\r'}"
API_KEY="${API_KEY%\"}"; API_KEY="${API_KEY#\"}"

if [ -z "${API_KEY:-}" ]; then
  echo "no engine API key (JARVIS_API_KEY unset and engine/.env has none) — skipping cross-check" >&2
  exit 3
fi

# -f makes curl exit non-zero and suppress the body on HTTP >= 400, so a 401
# (stale key) or 404/500 is reported as a failure rather than printed as if it
# were drift data. -sS keeps it quiet but still shows transport errors.
get() {
  local path="$1"
  if ! curl -fsS -X GET -H "X-API-Key: $API_KEY" "$BASE$path"; then
    echo "cross-check FAILED: GET $path returned a non-2xx / transport error — treat as unreachable, not drift" >&2
    exit 4
  fi
  echo
}

echo "# /prices/snapshot?symbols=$SYMBOL"
get "/prices/snapshot?symbols=$SYMBOL"

if [ "$ENGINE_TF" = "none" ]; then
  echo "# levels skipped — price-only mode (no exact engine timeframe for the charted TF)"
else
  echo "# /hidden-pivots/levels/$SYMBOL?timeframe=$ENGINE_TF"
  get "/hidden-pivots/levels/$SYMBOL?timeframe=$ENGINE_TF"
fi
