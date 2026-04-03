#!/usr/bin/env bash
# JARVIS TRADER — RL Run Launcher
# =================================
# Launches a PPO training run via the engine API.
# Prints the run_id and optionally starts monitoring.
#
# Usage:
#   bash scripts/launch_run9.sh [--symbol MES] [--timesteps 500000] [--monitor]
#
# Examples:
#   bash scripts/launch_run9.sh                              # MES, 500k steps
#   bash scripts/launch_run9.sh --symbol MNQ --timesteps 100000
#   bash scripts/launch_run9.sh --monitor                    # launch + monitor

set -euo pipefail

BASE_URL="http://localhost:8010"
SYMBOL="MES"
TIMESTEPS=500000
MONITOR=false

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
        --symbol)     SYMBOL="${2^^}"; shift 2 ;;
        --timesteps)  TIMESTEPS="$2"; shift 2 ;;
        --monitor)    MONITOR=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--symbol SYM] [--timesteps N] [--monitor]"
            echo "  --symbol     Symbol to train (default: MES)"
            echo "  --timesteps  PPO training steps (default: 500000)"
            echo "  --monitor    Start monitoring loop after launch"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── JSON helper ───────────────────────────────────────────────────────────────
json_get() {
    local json="$1"
    local key="$2"
    if command -v jq &>/dev/null; then
        echo "$json" | jq -r ".$key // empty"
    else
        python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('$key',''))" "$json" 2>/dev/null || true
    fi
}

# ── Engine health check ───────────────────────────────────────────────────────
echo -e "${BOLD}JARVIS TRADER — RL Run Launcher${RESET}"
echo "────────────────────────────────────────────────────────────"
echo -e "Symbol:     ${CYAN}${SYMBOL}${RESET}"
printf "Timesteps:  %'d\n" "$TIMESTEPS"
echo ""

echo -n "Checking engine health... "
health=$(curl -sf "$BASE_URL/health" 2>/dev/null || echo "")
if [[ -z "$health" ]]; then
    echo -e "${RED}FAILED${RESET}"
    echo ""
    echo -e "${RED}ERROR: Engine not responding at $BASE_URL${RESET}"
    echo "Start the engine first:"
    echo "  cd engine && .venv\\Scripts\\python -m uvicorn main:app --port 8010"
    exit 1
fi
echo -e "${GREEN}OK${RESET}"

# ── Check if already training ─────────────────────────────────────────────────
echo -n "Checking training state... "
status_resp=$(curl -sf "$BASE_URL/strategies/rl/status" 2>/dev/null || echo '{"state":"unknown"}')
current_state=$(json_get "$status_resp" "state")
echo -e "${CYAN}${current_state:-unknown}${RESET}"

if [[ "$current_state" == "training" || "$current_state" == "running" ]]; then
    current_symbol=$(json_get "$status_resp" "symbol")
    progress=$(json_get "$status_resp" "progress_pct")
    echo ""
    echo -e "${YELLOW}WARNING: Training already in progress!${RESET}"
    echo "  Symbol: ${current_symbol:-unknown} | Progress: ${progress:-?}%"
    echo ""
    read -rp "Stop existing run and launch new one? [y/N] " confirm
    if [[ "${confirm,,}" != "y" ]]; then
        echo "Aborted. Monitor existing run:"
        echo "  bash scripts/monitor_run9.sh --symbol ${current_symbol:-$SYMBOL}"
        exit 0
    fi
    echo -n "Stopping existing run... "
    curl -sf -X POST "$BASE_URL/strategies/rl/stop" > /dev/null 2>&1 || true
    sleep 2
    echo -e "${GREEN}stopped${RESET}"
fi

# ── Launch training ───────────────────────────────────────────────────────────
echo ""
echo -n "Launching training run... "
payload="{\"symbol\":\"${SYMBOL}\",\"timesteps\":${TIMESTEPS},\"interval\":\"1h\"}"
response=$(curl -sf -X POST \
    -H "Content-Type: application/json" \
    -d "$payload" \
    "$BASE_URL/strategies/rl/train" 2>/dev/null || echo "")

if [[ -z "$response" ]]; then
    echo -e "${RED}FAILED${RESET}"
    echo ""
    echo -e "${RED}ERROR: No response from /strategies/rl/train${RESET}"
    echo "Check engine logs for details."
    exit 1
fi

run_id=$(json_get "$response" "run_id")
status=$(json_get "$response" "status")

echo -e "${GREEN}LAUNCHED${RESET}"
echo ""
echo "────────────────────────────────────────────────────────────"
echo -e "  ${BOLD}Run ID:${RESET}     ${run_id:-N/A}"
echo -e "  ${BOLD}Symbol:${RESET}     ${SYMBOL}"
printf "  ${BOLD}Timesteps:${RESET}  %'d\n" "$TIMESTEPS"
echo -e "  ${BOLD}Status:${RESET}     ${status:-launched}"
echo "────────────────────────────────────────────────────────────"
echo ""
echo "Monitor:   bash scripts/monitor_run9.sh --symbol $SYMBOL"
echo "Evaluate:  python scripts/eval_run9.py --symbol $SYMBOL"
echo "Stop:      curl -X POST $BASE_URL/strategies/rl/stop"
echo ""

# ── Optional: start monitoring ────────────────────────────────────────────────
if [[ "$MONITOR" == "true" ]]; then
    echo -e "Starting monitor in 2s..."
    sleep 2
    exec bash "$(dirname "$0")/monitor_run9.sh" --symbol "$SYMBOL"
fi
