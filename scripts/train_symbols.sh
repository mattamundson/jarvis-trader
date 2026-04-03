#!/usr/bin/env bash
# JARVIS TRADER — Multi-Symbol RL Trainer
# =========================================
# Trains PPO models for all 4 supported symbols sequentially.
# Waits for each run to complete before starting the next.
#
# Usage:
#   bash scripts/train_symbols.sh [--timesteps 500000] [--symbols "MES MNQ MCL MGC"]
#
# Examples:
#   bash scripts/train_symbols.sh                             # all 4, 500k steps each
#   bash scripts/train_symbols.sh --timesteps 10000           # quick smoke test
#   bash scripts/train_symbols.sh --symbols "MNQ MCL"         # specific symbols only

set -euo pipefail

BASE_URL="http://localhost:8010"
TIMESTEPS=500000
SYMBOLS=("MES" "MNQ" "MCL" "MGC")
POLL_INTERVAL=30
MAX_WAIT_MINUTES=180   # 3h timeout per symbol

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
        --timesteps)
            TIMESTEPS="$2"; shift 2 ;;
        --symbols)
            IFS=' ' read -ra SYMBOLS <<< "$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--timesteps N] [--symbols \"SYM1 SYM2 ...\"]"
            exit 0 ;;
        *)
            echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── JSON helper ───────────────────────────────────────────────────────────────
json_get() {
    local json="$1"
    local key="$2"
    if command -v jq &>/dev/null; then
        echo "$json" | jq -r ".$key // empty" 2>/dev/null || echo ""
    else
        python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('$key',''))" "$json" 2>/dev/null || echo ""
    fi
}

# ── Engine health check ───────────────────────────────────────────────────────
echo -e "${BOLD}JARVIS TRADER — Multi-Symbol RL Trainer${RESET}"
echo "════════════════════════════════════════════════════════════"
printf "Symbols:    %s\n" "${SYMBOLS[*]}"
printf "Timesteps:  %'d per symbol\n" "$TIMESTEPS"
echo "════════════════════════════════════════════════════════════"
echo ""

if ! curl -sf "$BASE_URL/health" > /dev/null 2>&1; then
    echo -e "${RED}ERROR: Engine not responding at $BASE_URL${RESET}"
    echo "Start the engine: cd engine && .venv\\Scripts\\python -m uvicorn main:app --port 8010"
    exit 1
fi
echo -e "Engine: ${GREEN}OK${RESET}"
echo ""

# ── Per-symbol result tracking ────────────────────────────────────────────────
declare -A RESULTS_STATUS
declare -A RESULTS_TRADES
declare -A RESULTS_PF
declare -A RESULTS_SHARPE
declare -A RESULTS_WR
declare -A RESULTS_HOLD
declare -A RESULTS_GATES

# ── Train each symbol ─────────────────────────────────────────────────────────
for SYMBOL in "${SYMBOLS[@]}"; do
    SYMBOL="${SYMBOL^^}"
    echo -e "────────────────────────────────────────────────────────────"
    echo -e "${BOLD}Training ${CYAN}${SYMBOL}${RESET}${BOLD} (${TIMESTEPS} steps)${RESET}"
    echo -e "────────────────────────────────────────────────────────────"
    start_ts=$(date +%s)

    # Launch training
    payload="{\"symbol\":\"${SYMBOL}\",\"timesteps\":${TIMESTEPS},\"interval\":\"1h\"}"
    launch_resp=$(curl -sf -X POST \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$BASE_URL/strategies/rl/train" 2>/dev/null || echo "")

    if [[ -z "$launch_resp" ]]; then
        echo -e "${RED}ERROR: Failed to launch training for ${SYMBOL}${RESET}"
        RESULTS_STATUS[$SYMBOL]="LAUNCH_FAILED"
        continue
    fi

    run_id=$(json_get "$launch_resp" "run_id")
    echo -e "  Launched | Run ID: ${run_id:-N/A}"

    # Poll until done
    max_polls=$(( MAX_WAIT_MINUTES * 60 / POLL_INTERVAL ))
    poll_count=0
    final_state="unknown"

    while [[ $poll_count -lt $max_polls ]]; do
        sleep "$POLL_INTERVAL"
        poll_count=$(( poll_count + 1 ))

        status_resp=$(curl -sf "$BASE_URL/strategies/rl/status" 2>/dev/null || echo '{"state":"error"}')
        state=$(json_get "$status_resp" "state")
        progress=$(json_get "$status_resp" "progress_pct")
        n_trades=$(json_get "$status_resp" "n_trades")
        hold_rate=$(json_get "$status_resp" "hold_rate")
        elapsed=$(( $(date +%s) - start_ts ))
        elapsed_min=$(( elapsed / 60 ))

        printf "  [%02dm] State: %-12s Progress: %5s%%  trades: %s  hold: %s\n" \
            "$elapsed_min" "$state" "${progress:-?}" "${n_trades:-?}" "${hold_rate:-?}"

        if [[ "$state" == "completed" ]]; then
            final_state="completed"
            # Capture final metrics
            RESULTS_TRADES[$SYMBOL]=$(json_get "$status_resp" "n_trades")
            RESULTS_PF[$SYMBOL]=$(json_get "$status_resp" "profit_factor")
            RESULTS_SHARPE[$SYMBOL]=$(json_get "$status_resp" "sharpe")
            RESULTS_WR[$SYMBOL]=$(json_get "$status_resp" "win_rate")
            RESULTS_HOLD[$SYMBOL]=$(json_get "$status_resp" "hold_rate")
            # Determine gate count
            gates_passed=$(json_get "$status_resp" "gates_passed")
            RESULTS_GATES[$SYMBOL]="${gates_passed:-?}/6"
            break
        elif [[ "$state" == "failed" ]]; then
            final_state="failed"
            err=$(json_get "$status_resp" "error")
            echo -e "  ${RED}FAILED: ${err:-unknown error}${RESET}"
            break
        fi
    done

    if [[ "$final_state" == "completed" ]]; then
        RESULTS_STATUS[$SYMBOL]="COMPLETED"
        elapsed=$(( $(date +%s) - start_ts ))
        echo -e "  ${GREEN}COMPLETED${RESET} in $(( elapsed / 60 ))m$(( elapsed % 60 ))s"
        echo -e "  trades=${RESULTS_TRADES[$SYMBOL]} | PF=${RESULTS_PF[$SYMBOL]} | Sharpe=${RESULTS_SHARPE[$SYMBOL]} | WR=${RESULTS_WR[$SYMBOL]} | hold=${RESULTS_HOLD[$SYMBOL]}"
    elif [[ "$final_state" == "failed" ]]; then
        RESULTS_STATUS[$SYMBOL]="FAILED"
        RESULTS_TRADES[$SYMBOL]="-"
        RESULTS_PF[$SYMBOL]="-"
        RESULTS_SHARPE[$SYMBOL]="-"
        RESULTS_WR[$SYMBOL]="-"
        RESULTS_HOLD[$SYMBOL]="-"
        RESULTS_GATES[$SYMBOL]="-"
    else
        echo -e "  ${YELLOW}TIMEOUT after ${MAX_WAIT_MINUTES}m${RESET}"
        RESULTS_STATUS[$SYMBOL]="TIMEOUT"
        RESULTS_TRADES[$SYMBOL]="-"
        RESULTS_PF[$SYMBOL]="-"
        RESULTS_SHARPE[$SYMBOL]="-"
        RESULTS_WR[$SYMBOL]="-"
        RESULTS_HOLD[$SYMBOL]="-"
        RESULTS_GATES[$SYMBOL]="-"
    fi
    echo ""
done

# ── Final summary table ───────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
echo -e "${BOLD}  MULTI-SYMBOL TRAINING SUMMARY${RESET}"
echo "════════════════════════════════════════════════════════════"
printf "  %-6s  %-12s  %8s  %6s  %7s  %6s  %9s  %7s\n" \
    "Symbol" "Status" "n_trades" "PF" "Sharpe" "WR" "hold_rate" "Gates"
echo "  ──────  ────────────  ────────  ──────  ───────  ──────  ─────────  ───────"

exit_code=0
for SYMBOL in "${SYMBOLS[@]}"; do
    SYMBOL="${SYMBOL^^}"
    status="${RESULTS_STATUS[$SYMBOL]:-SKIPPED}"
    trades="${RESULTS_TRADES[$SYMBOL]:--}"
    pf="${RESULTS_PF[$SYMBOL]:--}"
    sharpe="${RESULTS_SHARPE[$SYMBOL]:--}"
    wr="${RESULTS_WR[$SYMBOL]:--}"
    hold="${RESULTS_HOLD[$SYMBOL]:--}"
    gates="${RESULTS_GATES[$SYMBOL]:--}"

    if [[ "$status" == "COMPLETED" && "$gates" == "6/6" ]]; then
        color="$GREEN"
    elif [[ "$status" == "COMPLETED" ]]; then
        color="$YELLOW"
        exit_code=1
    else
        color="$RED"
        exit_code=1
    fi

    printf "  ${color}%-6s  %-12s  %8s  %6s  %7s  %6s  %9s  %7s${RESET}\n" \
        "$SYMBOL" "$status" "$trades" "$pf" "$sharpe" "$wr" "$hold" "$gates"
done

echo "════════════════════════════════════════════════════════════"
echo ""
if [[ $exit_code -eq 0 ]]; then
    echo -e "${GREEN}All symbols passed validation. Ready for walk-forward and paper deployment.${RESET}"
else
    echo -e "${YELLOW}Some symbols need tuning. Review failed gates per symbol:${RESET}"
    echo "  python scripts/eval_run9.py --symbol <SYMBOL>"
    echo "  See docs/rl-run7-decision-tree.md for reward tuning scenarios."
fi
echo ""
exit $exit_code
