#!/bin/bash
#
# JARVIS TRADER — Graceful Shutdown
# ==================================
# Safely stops the trading system with proper order:
# 1. Activate kill switch (safety first)
# 2. Wait for pending orders to complete
# 3. Stop engine and dashboard
# 4. Generate end-of-day report
# 5. Optionally stop Docker containers
#
# Usage:
#   ./scripts/stop_trading.sh              # Full graceful shutdown
#   ./scripts/stop_trading.sh --force      # Force shutdown (skip safety wait)
#   ./scripts/stop_trading.sh --keep-docker # Stop apps but keep containers running
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Options
FORCE_SHUTDOWN=false
KEEP_DOCKER=false

# Parse command line args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) FORCE_SHUTDOWN=true; shift ;;
        --keep-docker) KEEP_DOCKER=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Get absolute paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOGS_DIR="$PROJECT_ROOT/logs"

mkdir -p "$LOGS_DIR"

# ── Helper Functions ──────────────────────────────────────────────────────────

log_step() {
    local num="$1"
    local msg="$2"
    echo ""
    echo -e "${CYAN}[${num}]${NC} ${msg}"
}

log_ok() {
    echo -e "  ${GREEN}✓${NC} $1"
}

log_wait() {
    echo -e "  ${YELLOW}→${NC} $1"
}

log_error() {
    echo -e "  ${RED}✗${NC} $1"
}

# ── Banner ────────────────────────────────────────────────────────────────────

echo ""
echo "$(printf '%*s\n' "${COLUMNS:-70}" '' | tr ' ' '=')"
echo -e "  ${CYAN}JARVIS TRADER — Graceful Shutdown${NC}"
echo "$(printf '%*s\n' "${COLUMNS:-70}" '' | tr ' ' '=')"
echo ""

# ── Step 1: Activate Kill Switch ──────────────────────────────────────────────

log_step "1/5" "Activating kill switch (safety first)..."

KILL_SWITCH_RESPONSE=$(curl -s --max-time 5 -X POST http://localhost:8010/safety/kill-switch/activate 2>/dev/null || echo '{}')

if echo "$KILL_SWITCH_RESPONSE" | grep -q "true\|active"; then
    log_ok "Kill switch activated"
else
    log_wait "Kill switch endpoint not responding (engine may not be running)"
fi

# ── Step 2: Wait for Pending Orders ───────────────────────────────────────────

if [[ "$FORCE_SHUTDOWN" == false ]]; then
    log_step "2/5" "Waiting for pending orders to complete (5 seconds grace period)..."

    for i in {5..1}; do
        echo -ne "\r  Waiting... ${i}s remaining"
        sleep 1
    done
    echo -e "\n  ${GREEN}✓${NC} Grace period complete"
    log_ok "Ready to shutdown"
else
    log_step "2/5" "Skipping grace period (--force flag)"
fi

# ── Step 3: Stop Engine ───────────────────────────────────────────────────────

log_step "3/5" "Stopping engine..."

# Try graceful shutdown via API first
if curl -s --max-time 2 http://localhost:8010/health > /dev/null 2>&1; then
    # Kill Python processes on port 8010
    if lsof -i :8010 > /dev/null 2>&1; then
        kill $(lsof -t -i :8010) 2>/dev/null || true
        sleep 2
        log_ok "Engine stopped"
    else
        log_wait "No process found on port 8010"
    fi
else
    log_wait "Engine not responding (may already be stopped)"
fi

# ── Step 4: Stop Dashboard ────────────────────────────────────────────────────

log_step "4/5" "Stopping dashboard..."

if lsof -i :3010 > /dev/null 2>&1; then
    kill $(lsof -t -i :3010) 2>/dev/null || true
    sleep 1
    log_ok "Dashboard stopped"
else
    log_wait "No process found on port 3010 (may already be stopped)"
fi

# ── Step 5: Docker Cleanup ────────────────────────────────────────────────────

if [[ "$KEEP_DOCKER" == false ]]; then
    log_step "5/5" "Stopping Docker Compose stack..."

    cd "$PROJECT_ROOT/infrastructure"
    if docker compose ps 2>/dev/null | grep -q "jarvis_"; then
        docker compose down 2>&1 | grep -E "Container|Removing|Network" || true
        log_ok "Docker containers stopped"
    else
        log_wait "No Docker containers running"
    fi
    cd "$PROJECT_ROOT"
else
    log_step "5/5" "Skipping Docker shutdown (--keep-docker flag)"
fi

# ── Generate End-of-Day Report ────────────────────────────────────────────────

echo ""
log_wait "Generating end-of-day report..."

if curl -s --max-time 5 http://localhost:8010/portfolio/history/daily-pnl > /dev/null 2>&1; then
    bash "$SCRIPT_DIR/daily_report.sh" --save --json > /dev/null 2>&1 || true
    log_ok "Daily report saved to logs/daily_reports.log"
else
    log_wait "Engine not available (skipping daily report)"
fi

# ── Shutdown Complete ─────────────────────────────────────────────────────────

echo ""
echo "$(printf '%*s\n' "${COLUMNS:-70}" '' | tr ' ' '=')"
echo -e "  ${GREEN}JARVIS TRADER shutdown complete${NC}"
echo "$(printf '%*s\n' "${COLUMNS:-70}" '' | tr ' ' '=')"
echo ""
echo "  Logs saved to: $LOGS_DIR"
echo "  Daily reports: $LOGS_DIR/daily_reports.log"
echo ""
echo "  To restart trading:"
echo "    ./scripts/start_paper_trading.sh"
echo ""
echo "$(printf '%*s\n' "${COLUMNS:-70}" '' | tr ' ' '=')"
echo ""
