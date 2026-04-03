#!/bin/bash
#
# JARVIS TRADER — System Health Check
# ===================================
# Quick validation that all components are healthy and ready for trading.
# Run this before starting paper trading or anytime you want a system status.
#
# Usage:
#   ./scripts/health_check.sh              # Check all components
#   ./scripts/health_check.sh --quiet      # Quiet mode (no banner, exit code only)
#
# Exit codes:
#   0 = All checks passed (GREEN)
#   1 = At least one check failed (RED)
#

set -e

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

QUIET_MODE=false
FAILED_CHECKS=0

# Parse command line args
if [[ "$1" == "--quiet" ]]; then
    QUIET_MODE=true
fi

# ── Helper functions ──────────────────────────────────────────────────────────

print_banner() {
    if [[ "$QUIET_MODE" == false ]]; then
        echo ""
        echo "$(printf '%*s\n' "${COLUMNS:-60}" '' | tr ' ' '=')"
        echo "  JARVIS TRADER — System Health Check"
        echo "$(printf '%*s\n' "${COLUMNS:-60}" '' | tr ' ' '=')"
        echo ""
    fi
}

check_pass() {
    local name="$1"
    if [[ "$QUIET_MODE" == false ]]; then
        echo -e "  ${GREEN}✓${NC} $name"
    fi
}

check_fail() {
    local name="$1"
    local reason="$2"
    if [[ "$QUIET_MODE" == false ]]; then
        echo -e "  ${RED}✗${NC} $name"
        if [[ -n "$reason" ]]; then
            echo -e "    ${RED}→${NC} $reason"
        fi
    fi
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
}

check_section() {
    if [[ "$QUIET_MODE" == false ]]; then
        echo ""
        echo -e "${BLUE}${1}${NC}"
    fi
}

# ── Health Checks ─────────────────────────────────────────────────────────────

print_banner

# 1. Engine Health
check_section "Engine API (localhost:8010)"
if curl -s --max-time 2 http://localhost:8010/health > /dev/null 2>&1; then
    check_pass "Engine responding"
else
    check_fail "Engine responding" "curl http://localhost:8010/health failed"
fi

# 2. Dashboard Health
check_section "Dashboard (localhost:3010)"
if curl -s --max-time 2 http://localhost:3010 > /dev/null 2>&1; then
    check_pass "Dashboard responding"
else
    check_fail "Dashboard responding" "curl http://localhost:3010 failed"
fi

# 3. Kill Switch Status
check_section "Safety - Kill Switch (localhost:8010/safety/status)"
if curl -s --max-time 2 http://localhost:8010/safety/status > /dev/null 2>&1; then
    check_pass "Kill switch accessible"
else
    check_fail "Kill switch accessible" "curl http://localhost:8010/safety/status failed"
fi

# 4. Docker Containers
check_section "Docker Containers"
required_containers=("jarvis_postgres" "jarvis_redis" "jarvis_questdb" "jarvis_prometheus" "jarvis_grafana")

for container in "${required_containers[@]}"; do
    if docker ps --filter "name=$container" --filter "status=running" --quiet | grep -q .; then
        check_pass "Container: $container"
    else
        check_fail "Container: $container" "Not running (check: docker compose ps)"
    fi
done

# 5. Paper Trading Mode
check_section "Paper Trading Configuration"
if curl -s --max-time 2 http://localhost:8010/settings/risk > /dev/null 2>&1; then
    check_pass "Risk settings accessible"
else
    check_fail "Risk settings accessible" "curl http://localhost:8010/settings/risk failed"
fi

# 6. Portfolio Access
check_section "Portfolio API"
if curl -s --max-time 2 http://localhost:8010/portfolio/paper/positions > /dev/null 2>&1; then
    check_pass "Paper positions endpoint"
else
    check_fail "Paper positions endpoint" "curl http://localhost:8010/portfolio/paper/positions failed"
fi

# ── Summary ───────────────────────────────────────────────────────────────────

if [[ "$QUIET_MODE" == false ]]; then
    echo ""
    echo "$(printf '%*s\n' "${COLUMNS:-60}" '' | tr ' ' '=')"
fi

if [[ $FAILED_CHECKS -eq 0 ]]; then
    if [[ "$QUIET_MODE" == false ]]; then
        echo -e "  ${GREEN}All checks passed - System ready for trading${NC}"
        echo "$(printf '%*s\n' "${COLUMNS:-60}" '' | tr ' ' '=')"
        echo ""
    fi
    exit 0
else
    if [[ "$QUIET_MODE" == false ]]; then
        echo -e "  ${RED}$FAILED_CHECKS check(s) failed - System not ready${NC}"
        echo "$(printf '%*s\n' "${COLUMNS:-60}" '' | tr ' ' '=')"
        echo ""
        echo "  Debug tips:"
        echo "    • Engine logs:   engine/logs/jarvis_trader.log"
        echo "    • Docker status: docker compose ps"
        echo "    • Container logs: docker logs <container_name>"
        echo ""
    fi
    exit 1
fi
