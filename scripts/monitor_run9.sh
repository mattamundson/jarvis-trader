#!/usr/bin/env bash
# JARVIS TRADER — RL Training Monitor
# =====================================
# Polls /strategies/rl/status every N seconds and prints progress.
# Press Ctrl+C to stop monitoring (training continues in background).
#
# Usage:
#   bash scripts/monitor_run9.sh [--interval 30] [--symbol MES]
#
# Examples:
#   bash scripts/monitor_run9.sh
#   bash scripts/monitor_run9.sh --interval 10 --symbol MNQ

set -euo pipefail

BASE_URL="http://localhost:8010"
INTERVAL=30
SYMBOL="MES"
IDLE_EXIT_COUNT=3
idle_count=0

# ── ANSI colors ───────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --interval) INTERVAL="$2"; shift 2 ;;
        --symbol)   SYMBOL="${2^^}"; shift 2 ;;
        *)          echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Cleanup handler ───────────────────────────────────────────────────────────
cleanup() {
    echo -e "\n${CYAN}Monitoring stopped. Training continues in background.${RESET}"
    echo "  Resume monitoring:  bash scripts/monitor_run9.sh --symbol $SYMBOL"
    echo "  Evaluate when done: python scripts/eval_run9.py --symbol $SYMBOL"
    exit 0
}
trap cleanup INT TERM

# ── JSON helper (python3 fallback if jq not available) ────────────────────────
json_get() {
    local json="$1"
    local key="$2"
    if command -v jq &>/dev/null; then
        echo "$json" | jq -r ".$key // \"N/A\""
    else
        python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('$key','N/A'))" "$json" 2>/dev/null || echo "N/A"
    fi
}

# ── Check engine reachability ─────────────────────────────────────────────────
echo -e "${BOLD}JARVIS TRADER — RL Training Monitor${RESET}"
echo -e "Symbol: ${CYAN}${SYMBOL}${RESET} | Polling every ${INTERVAL}s | Ctrl+C to stop"
echo "────────────────────────────────────────────────────────────"

if ! curl -sf "$BASE_URL/health" > /dev/null 2>&1; then
    echo -e "${RED}ERROR: Engine not responding at $BASE_URL${RESET}"
    echo "Start the engine: cd engine && .venv\\Scripts\\python -m uvicorn main:app --port 8010"
    exit 1
fi

# ── Main polling loop ─────────────────────────────────────────────────────────
while true; do
    timestamp=$(date +"%H:%M:%S")

    # Fetch status
    response=$(curl -sf "$BASE_URL/strategies/rl/status" 2>/dev/null || echo '{"state":"error"}')

    state=$(json_get "$response" "state")
    progress=$(json_get "$response" "progress_pct")
    step=$(json_get "$response" "current_step")
    total_steps=$(json_get "$response" "total_steps")
    symbol_status=$(json_get "$response" "symbol")
    n_trades=$(json_get "$response" "n_trades")
    hold_rate=$(json_get "$response" "hold_rate")
    error_msg=$(json_get "$response" "error")

    case "$state" in
        "training"|"running")
            idle_count=0
            # Format progress bar
            pct=${progress/.*}  # truncate to int
            pct=${pct:-0}
            bar_len=20
            filled=$(( pct * bar_len / 100 ))
            bar=$(printf '#%.0s' $(seq 1 $filled 2>/dev/null || echo 1))
            empty=$(printf '.%.0s' $(seq 1 $(( bar_len - filled )) 2>/dev/null || echo 1))
            echo -e "${YELLOW}[${timestamp}]${RESET} ${CYAN}${symbol_status:-$SYMBOL}${RESET} | State: ${YELLOW}TRAINING${RESET} | [${bar}${empty}] ${pct}% | Step: ${step:-?}/${total_steps:-?} | trades: ${n_trades:-0} | hold: ${hold_rate:-N/A}"
            ;;

        "completed")
            pf=$(json_get "$response" "profit_factor")
            wr=$(json_get "$response" "win_rate")
            sharpe=$(json_get "$response" "sharpe")
            echo -e "${GREEN}[${timestamp}]${RESET} ${CYAN}${symbol_status:-$SYMBOL}${RESET} | State: ${GREEN}COMPLETED${RESET}"
            echo -e "  trades=${n_trades} | hold_rate=${hold_rate} | PF=${pf} | WR=${wr} | Sharpe=${sharpe}"
            echo ""
            echo -e "${GREEN}Training complete.${RESET}"
            echo "  Evaluate: python scripts/eval_run9.py --symbol ${symbol_status:-$SYMBOL}"
            echo "  Launch next: bash scripts/launch_run9.sh"
            exit 0
            ;;

        "failed")
            echo -e "${RED}[${timestamp}]${RESET} ${CYAN}${symbol_status:-$SYMBOL}${RESET} | State: ${RED}FAILED${RESET} | Error: ${error_msg:-unknown}"
            echo ""
            echo -e "${RED}Training failed.${RESET} Check engine logs for details."
            exit 1
            ;;

        "idle"|"N/A")
            idle_count=$(( idle_count + 1 ))
            echo -e "${YELLOW}[${timestamp}]${RESET} No training in progress (idle). Check ${idle_count}/${IDLE_EXIT_COUNT}"
            if [[ $idle_count -ge $IDLE_EXIT_COUNT ]]; then
                echo "No training detected after $IDLE_EXIT_COUNT checks. Exiting."
                echo "  Launch training: bash scripts/launch_run9.sh"
                exit 0
            fi
            ;;

        "error")
            echo -e "${RED}[${timestamp}]${RESET} ${RED}ERROR: Could not reach engine status endpoint${RESET}"
            ;;

        *)
            echo -e "[${timestamp}] State: ${state} | ${response:0:120}"
            ;;
    esac

    sleep "$INTERVAL"
done
