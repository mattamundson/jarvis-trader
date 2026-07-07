#!/bin/bash
# scripts/verify_dashboard_build.sh
# Verifies that the dashboard builds successfully and reports route/error summary.
#
# Exit codes:
#   0 - Build successful
#   1 - Build failed or dependencies missing
#
# Usage:
#   bash scripts/verify_dashboard_build.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DASHBOARD_DIR="${PROJECT_ROOT}/dashboard"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}JARVIS TRADER Dashboard Build Verification${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Check if dashboard directory exists
if [ ! -d "$DASHBOARD_DIR" ]; then
    echo -e "${RED}Error: Dashboard directory not found at $DASHBOARD_DIR${NC}"
    exit 1
fi

cd "$DASHBOARD_DIR"

# Install pnpm if not available
if ! command -v pnpm &> /dev/null; then
    echo -e "${YELLOW}Installing pnpm...${NC}"
    npm install -g pnpm --prefix ~/.npm-global 2>&1 | tail -2
    export PATH=~/.npm-global/bin:$PATH
fi

# Install dependencies if node_modules is missing
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing dashboard dependencies...${NC}"
    export CI=true
    pnpm install --frozen-lockfile 2>&1 | tail -5
fi

# Run the build
echo -e "${YELLOW}Running dashboard build...${NC}"
echo ""

if pnpm run build 2>&1 | tee /tmp/dashboard_build.log; then
    echo ""
    echo -e "${GREEN}✓ Dashboard build successful${NC}"

    # Count routes and report summary
    if [ -d ".next" ]; then
        ROUTE_COUNT=$(find .next -name "*.js" -o -name "*.json" | wc -l)
        echo -e "${GREEN}✓ Build artifacts generated (${ROUTE_COUNT} files in .next)${NC}"
    fi

    # Check for TypeScript errors in the build log
    if grep -i "typescript error\|error TS" /tmp/dashboard_build.log &> /dev/null; then
        echo -e "${RED}✗ TypeScript errors detected during build${NC}"
        exit 1
    fi

    # Check for warnings (but don't fail)
    if grep -i "warning\|deprecated" /tmp/dashboard_build.log &> /dev/null; then
        echo -e "${YELLOW}⚠ Build warnings detected (see log for details)${NC}"
    fi

    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}Dashboard Build Status: PASS${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    exit 0
else
    echo ""
    echo -e "${RED}✗ Dashboard build failed${NC}"

    # Extract and display relevant error lines
    if [ -f /tmp/dashboard_build.log ]; then
        echo ""
        echo -e "${RED}Build errors:${NC}"
        grep -E "error|Error|ERROR|TS[0-9]{4}" /tmp/dashboard_build.log | head -20
    fi

    echo ""
    echo -e "${RED}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${RED}Dashboard Build Status: FAIL${NC}"
    echo -e "${RED}═══════════════════════════════════════════════════════════════${NC}"
    exit 1
fi
