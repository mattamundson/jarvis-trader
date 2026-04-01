#!/bin/bash
#
# JARVIS TRADER — Daily Report
# ============================
# End-of-day summary script that fetches P&L, trade counts, and safety events.
# Generates a clean terminal report and optionally appends to daily_reports.log
#
# Usage:
#   ./scripts/daily_report.sh                  # Print report to terminal
#   ./scripts/daily_report.sh --save           # Save to logs/daily_reports.log
#   ./scripts/daily_report.sh --save --json    # Output as JSON (for integration)
#

set -e

SAVE_LOG=false
JSON_MODE=false

# Parse command line args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --save) SAVE_LOG=true; shift ;;
        --json) JSON_MODE=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOGS_DIR="$PROJECT_ROOT/logs"
REPORT_FILE="$LOGS_DIR/daily_reports.log"

# Ensure logs directory exists
mkdir -p "$LOGS_DIR"

# Helper to safely fetch from API with timeout
fetch_api() {
    local endpoint="$1"
    local timeout="${2:-5}"
    curl -s --max-time "$timeout" "http://localhost:8010$endpoint" 2>/dev/null || echo "null"
}

# Helper to extract field from JSON
jq_extract() {
    local json="$1"
    local path="$2"
    echo "$json" | jq -r "$path" 2>/dev/null || echo "N/A"
}

# ── Fetch Data ────────────────────────────────────────────────────────────────

# Daily P&L
daily_pnl_json=$(fetch_api "/portfolio/history/daily-pnl")
total_pnl=$(jq_extract "$daily_pnl_json" '.today_pnl // 0')
today_trades=$(jq_extract "$daily_pnl_json" '.trade_count // 0')
win_rate=$(jq_extract "$daily_pnl_json" '.win_rate // 0')

# Loss tracker for consecutive losses
loss_tracker_json=$(fetch_api "/safety/loss-tracker")
consecutive_losses=$(jq_extract "$loss_tracker_json" '.consecutive_losses // 0')
max_daily_loss=$(jq_extract "$loss_tracker_json" '.max_daily_loss // "N/A"')

# Safety status
safety_status_json=$(fetch_api "/safety/status")
kill_switch_active=$(jq_extract "$safety_status_json" '.kill_switch_active // false')
circuit_breakers=$(jq_extract "$safety_status_json" '.circuit_breakers_active // false')

# Portfolio stats
portfolio_json=$(fetch_api "/portfolio/stats/summary")
total_portfolio_value=$(jq_extract "$portfolio_json" '.total_value // "N/A"')
unrealized_pnl=$(jq_extract "$portfolio_json" '.unrealized_pnl // "N/A"')

# Paper trading positions
positions_json=$(fetch_api "/portfolio/paper/positions")
open_positions=$(jq_extract "$positions_json" '.positions | length // 0')

# Determine P&L color
if (( $(echo "$total_pnl < 0" | bc -l 2>/dev/null || echo 0) )); then
    pnl_color=$RED
elif (( $(echo "$total_pnl > 0" | bc -l 2>/dev/null || echo 0) )); then
    pnl_color=$GREEN
else
    pnl_color=$YELLOW
fi

# ── JSON Output ───────────────────────────────────────────────────────────────

if [[ "$JSON_MODE" == true ]]; then
    cat <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "daily_pnl": $total_pnl,
  "trades": $today_trades,
  "win_rate": $win_rate,
  "consecutive_losses": $consecutive_losses,
  "open_positions": $open_positions,
  "kill_switch_active": $kill_switch_active,
  "circuit_breakers_active": $circuit_breakers,
  "portfolio_value": "$total_portfolio_value",
  "unrealized_pnl": "$unrealized_pnl"
}
EOF
    exit 0
fi

# ── Terminal Report ───────────────────────────────────────────────────────────

report=$(cat <<EOF

$(printf '%*s\n' "${COLUMNS:-70}" '' | tr ' ' '=')
  JARVIS TRADER — Daily Report
  $(date +'%A, %B %d, %Y at %H:%M UTC')
$(printf '%*s\n' "${COLUMNS:-70}" '' | tr ' ' '=')

  Daily Performance
    Daily P&L:              ${pnl_color}${total_pnl}${NC}
    Trades Executed:        $today_trades
    Win Rate:               $win_rate%

  Risk & Safety
    Consecutive Losses:     $consecutive_losses
    Max Daily Loss Limit:   $max_daily_loss
    Kill Switch Active:     $([ "$kill_switch_active" = "true" ] && echo -e "${RED}YES${NC}" || echo -e "${GREEN}NO${NC}")
    Circuit Breakers:       $([ "$circuit_breakers" = "true" ] && echo -e "${RED}TRIGGERED${NC}" || echo -e "${GREEN}OK${NC}")

  Portfolio Status
    Total Value:            $total_portfolio_value
    Unrealized P&L:         $unrealized_pnl
    Open Positions:         $open_positions

$(printf '%*s\n' "${COLUMNS:-70}" '' | tr ' ' '=')

EOF
)

echo -e "$report"

# ── Save to Log ───────────────────────────────────────────────────────────────

if [[ "$SAVE_LOG" == true ]]; then
    echo -e "$report" >> "$REPORT_FILE"
    echo -e "${GREEN}✓ Report saved to: $REPORT_FILE${NC}"
fi
