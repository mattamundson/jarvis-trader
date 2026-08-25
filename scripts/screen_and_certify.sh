#!/usr/bin/env bash
# JARVIS screen → certify pipeline (one command).
#
# Screens a symbol's parameter grid with iterate.py (grid × VIX × MC),
# selects the top-N survivors, then certifies each through the
# env-parameterized gate-v2 WFO runner (run_equity_sma_cert.py). WFO cert is
# the referee — screening alone never adopts.
#
# Runs IN-PLACE in the main checkout: deep caches, engine/.venv and the
# verdicts dir all live there (gitignored), so an isolated worktree would lack
# all three. The pipeline writes only to gitignored runtime dirs
# (backtest/results/, data/gate_v2_verdicts/) — no git state is touched.
#
# Usage (from jarvis-trader root):
#   bash scripts/screen_and_certify.sh MES [--top 3] [--smoke] \
#       [--strategy trend] [--cache PATH] [--vix-csv PATH] \
#       [--vix-min X] [--vix-max Y] [--vix-regimes A,B] [--out PATH]
#
# Requires: engine/.venv, deep cache for the symbol.
# Refuses DO_NOT_TRADE symbols (MGC/MCL/MNQ/M2K).
set -euo pipefail

SYM="${1:?usage: screen_and_certify.sh SYMBOL [--top N] [--smoke] [--strategy trend] [--cache PATH] [--vix-csv PATH] [--vix-min X] [--vix-max Y] [--vix-regimes A,B] [--out PATH]}"
shift || true
TOP=3
SMOKE=""
STRATEGY="trend"
CACHE=""
OUT=""
VIX_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --top) TOP="$2"; shift 2 ;;
    --smoke) SMOKE="--smoke"; shift ;;
    --strategy) STRATEGY="$2"; shift 2 ;;
    --cache) CACHE="$2"; shift 2 ;;
    --vix-csv) VIX_ARGS+=(--vix-csv "$2"); shift 2 ;;
    --vix-min) VIX_ARGS+=(--vix-min "$2"); shift 2 ;;
    --vix-max) VIX_ARGS+=(--vix-max "$2"); shift 2 ;;
    --vix-regimes) VIX_ARGS+=(--vix-regimes "$2"); shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

ENGINE_ROOT="$(cd "$(dirname "$0")/.." && pwd)/engine"
PY="$ENGINE_ROOT/.venv/Scripts/python.exe"
STAMP="$(date +%Y-%m-%d)"
# Normalize user --out to an absolute path at parse time: run_py cd's into
# engine/, so a relative path would resolve under engine/ (nested dirs).
if [[ -n "$OUT" && "$OUT" != /* ]]; then
  OUT="$(pwd)/$OUT"
fi
OUT="${OUT:-$ENGINE_ROOT/backtest/results/iterate_${SYM}_${STAMP}.json}"

# Hard guard: DO_NOT_TRADE symbols (mirror of engine/backtest/signals.py).
case "$SYM" in
  MGC|MCL|MNQ|M2K)
    echo "REFUSED: $SYM is DO_NOT_TRADE_SYMBOLS — screening/certifying it is forbidden." >&2
    exit 2 ;;
esac

run_py() {
  (cd "$ENGINE_ROOT" && env -u PYTHONPATH -u PYTHONHOME "$PY" "$@")
}

echo "=== [1/3] Screen $SYM (grid × VIX × MC, strategy=$STRATEGY) ==="
run_py backtest/iterate.py --symbol "$SYM" --strategy "$STRATEGY" \
  ${CACHE:+--cache "$CACHE"} $SMOKE "${VIX_ARGS[@]}" \
  --out "$OUT" 2>&1 | tail -12

echo "=== [2/3] Select top $TOP candidates (trades>=10, p_edge>=0.6) ==="
CANDIDATES="$(run_py -m backtest.screen_cert_pipeline select --doc "$OUT" --top "$TOP" | tr -d '\r')"
if [[ -z "$CANDIDATES" ]]; then
  echo "No candidates passed the screen (trades>=10, p_edge>=0.6). Nothing to certify."
  exit 0
fi
echo "$CANDIDATES" | awk -F'\t' '{printf "  fast=%s slow=%s atr=%s p_edge=%s pf=%s trades=%s vix=%s\n", $1,$2,$3,$4,$5,$6,$7}'

echo "=== [3/3] Certify each candidate (env-parameterized gate-v2 WFO) ==="
echo "$CANDIDATES" | while IFS=$'\t' read -r FAST SLOW ATR P_EDGE PF TRADES VIX_BLOCK; do
  echo "--- certifying $SYM (fast=$FAST slow=$SLOW atr=$ATR) p_edge=$P_EDGE pf=$PF trades=$TRADES ---"
  CERT_ENV="$(run_py -m backtest.screen_cert_pipeline cert-env \
    --symbol "$SYM" --fast "$FAST" --slow "$SLOW" --atr "$ATR" \
    --strategy "$STRATEGY" ${SMOKE:+--smoke} ${CACHE:+--cache "$CACHE"} | tr -d '\r')"
  # shellcheck disable=SC2086
  (cd "$ENGINE_ROOT" && env -u PYTHONPATH -u PYTHONHOME \
    env $CERT_ENV "$PY" backtest/run_equity_sma_cert.py 2>&1 | tail -8)
done

echo "=== Done: $SYM screened + top-$TOP certified ==="
echo "    verdicts: engine/data/gate_v2_verdicts/${SYM}_sma_cert_*.json"
echo "    journal:  engine/data/gate_v2_verdicts/_journal.csv"
