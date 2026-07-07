#!/bin/bash
#
# JARVIS TRADER — Start Paper Trading (Linux/Mac)
# ================================================
# Complete startup script that initializes the entire trading environment.
# Complements the Windows start_jarvis.bat with Linux/Mac support.
#
# Prerequisites:
#   • Docker & Docker Compose installed
#   • Python 3.10+ in engine/.venv
#   • Node.js & npm in dashboard
#
# Usage:
#   ./scripts/start_paper_trading.sh              # Full startup
#   ./scripts/start_paper_trading.sh --no-browser # Skip browser open
#   ./scripts/start_paper_trading.sh --no-dashboard # Engine only (no dashboard)
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
OPEN_BROWSER=true
START_DASHBOARD=true
SKIP_DOCKER=false

# Parse command line args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-browser) OPEN_BROWSER=false; shift ;;
        --no-dashboard) START_DASHBOARD=false; shift ;;
        --skip-docker) SKIP_DOCKER=true; shift ;;
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

wait_for_service() {
    local url="$1"
    local name="$2"
    local max_attempts="${3:-30}"
    local attempt=0

    log_wait "Waiting for $name (max ${max_attempts} attempts)..."

    while [ $attempt -lt $max_attempts ]; do
        if curl -s --max-time 2 "$url" > /dev/null 2>&1; then
            log_ok "$name is ready"
            return 0
        fi
        attempt=$((attempt + 1))
        echo -n "."
        sleep 2
    done

    echo ""
    log_error "$name did not become healthy after ${max_attempts} attempts"
    return 1
}

# ── Check Prerequisites ───────────────────────────────────────────────────────

log_step "1/6" "Checking prerequisites..."

# Check .env
if [ ! -f "$PROJECT_ROOT/engine/.env" ]; then
    log_error "engine/.env not found"
    echo ""
    echo "  Please copy engine/.env.example to engine/.env and fill in your values:"
    echo "    cp $PROJECT_ROOT/engine/.env.example $PROJECT_ROOT/engine/.env"
    echo ""
    exit 1
fi
log_ok "engine/.env found"

# Check venv
if [ ! -d "$PROJECT_ROOT/engine/.venv" ]; then
    log_error "engine/.venv not found"
    echo ""
    echo "  Please set up Python virtual environment:"
    echo "    cd $PROJECT_ROOT/engine"
    echo "    python3 -m venv .venv"
    echo "    .venv/bin/pip install -r requirements.txt"
    echo ""
    exit 1
fi
log_ok "engine/.venv found"

# Check docker
if ! command -v docker &> /dev/null; then
    log_error "Docker not installed"
    exit 1
fi
log_ok "Docker installed"

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    log_error "Docker Compose not installed"
    exit 1
fi
log_ok "Docker Compose available"

# ── Initialize Database ──────────────────────────────────────────────────────

log_step "2/6" "Initializing database..."

cd "$PROJECT_ROOT/engine"
if [ -d ".venv" ]; then
    .venv/bin/python init_db.py > "$LOGS_DIR/init_db.log" 2>&1
    log_ok "Database initialized"
else
    log_error "Virtual environment not properly configured"
    exit 1
fi
cd "$PROJECT_ROOT"

# ── Start Docker Compose Stack ───────────────────────────────────────────────

if [[ "$SKIP_DOCKER" == false ]]; then
    log_step "3/6" "Starting Docker Compose stack (PostgreSQL, Redis, QuestDB, Prometheus, Grafana)..."

    cd "$PROJECT_ROOT/infrastructure"
    docker compose up -d 2>&1 | grep -E "Created|Starting|Container|already"
    cd "$PROJECT_ROOT"

    log_wait "Waiting for PostgreSQL..."
    wait_for_service "http://localhost:5432" "PostgreSQL" 15 || true

    log_wait "Waiting for Redis..."
    if docker exec jarvis_redis redis-cli ping &> /dev/null; then
        log_ok "Redis is ready"
    fi

    log_ok "Docker Compose stack started"
else
    log_step "3/6" "Skipping Docker (--skip-docker flag)"
fi

# ── Start Engine ──────────────────────────────────────────────────────────────

log_step "4/6" "Starting JARVIS Engine on port 8010..."

cd "$PROJECT_ROOT/engine"

# Check if already running
if curl -s --max-time 2 http://localhost:8010/health > /dev/null 2>&1; then
    log_ok "Engine already running"
else
    # Start in background
    nohup .venv/bin/python -m uvicorn main:app --port 8010 \
        > "$LOGS_DIR/engine.log" 2>&1 &
    ENGINE_PID=$!
    log_ok "Engine process started (PID: $ENGINE_PID)"

    # Wait for health check
    wait_for_service "http://localhost:8010/health" "Engine API" 30
fi

cd "$PROJECT_ROOT"

# ── Start Dashboard ───────────────────────────────────────────────────────────

if [[ "$START_DASHBOARD" == true ]]; then
    log_step "5/6" "Starting Dashboard on port 3010..."

    cd "$PROJECT_ROOT/dashboard"

    # Check if npm dependencies installed
    if [ ! -d "node_modules" ]; then
        log_wait "Installing npm dependencies (this may take a moment)..."
        npm install --legacy-peer-deps > "$LOGS_DIR/dashboard_npm.log" 2>&1
    fi

    # Check if already running
    if curl -s --max-time 2 http://localhost:3010 > /dev/null 2>&1; then
        log_ok "Dashboard already running"
    else
        # Start in background
        nohup npm run dev > "$LOGS_DIR/dashboard.log" 2>&1 &
        DASHBOARD_PID=$!
        log_ok "Dashboard process started (PID: $DASHBOARD_PID)"

        # Wait for health check
        wait_for_service "http://localhost:3010" "Dashboard" 30
    fi

    cd "$PROJECT_ROOT"
else
    log_step "5/6" "Skipping Dashboard (--no-dashboard flag)"
fi

# ── Run Health Check ──────────────────────────────────────────────────────────

log_step "6/6" "Running system health check..."

sleep 2
bash "$SCRIPT_DIR/health_check.sh" --quiet || {
    log_error "Health check failed. Check logs:"
    echo "    Engine:    $LOGS_DIR/engine.log"
    echo "    Dashboard: $LOGS_DIR/dashboard.log"
    echo "    Init:      $LOGS_DIR/init_db.log"
    exit 1
}

# ── Open Browser ──────────────────────────────────────────────────────────────

if [[ "$OPEN_BROWSER" == true && "$START_DASHBOARD" == true ]]; then
    sleep 1
    if command -v xdg-open &> /dev/null; then
        # Linux
        xdg-open http://localhost:3010 2>/dev/null || true
    elif command -v open &> /dev/null; then
        # macOS
        open http://localhost:3010 2>/dev/null || true
    fi
fi

# ── Startup Complete ──────────────────────────────────────────────────────────

echo ""
echo "$(printf '%*s\n' "${COLUMNS:-70}" '' | tr ' ' '=')"
echo -e "  ${GREEN}JARVIS TRADER is running${NC}"
echo "$(printf '%*s\n' "${COLUMNS:-70}" '' | tr ' ' '=')"
echo ""
echo "  Endpoints:"
echo "    • Engine:      http://localhost:8010"
echo "    • Dashboard:   http://localhost:3010"
echo "    • API Docs:    http://localhost:8010/docs"
echo "    • Grafana:     http://localhost:3030"
echo ""
echo "  Logs:"
echo "    • Engine:      $LOGS_DIR/engine.log"
echo "    • Dashboard:   $LOGS_DIR/dashboard.log"
echo ""
echo "  Next steps:"
echo "    1. Open dashboard at http://localhost:3010"
echo "    2. Configure paper trading parameters"
echo "    3. Start monitoring: ./scripts/daily_report.sh"
echo "    4. Stop trading:    ./scripts/stop_trading.sh"
echo ""
echo "$(printf '%*s\n' "${COLUMNS:-70}" '' | tr ' ' '=')"
echo ""
