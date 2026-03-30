#!/usr/bin/env python3
"""
Add Pydantic response models to main.py carefully.
"""

from pathlib import Path

main_file = Path("main.py")
content = main_file.read_text()

# Check if already updated
if "response_model=HealthResponse" in content:
    print("✅ main.py already has response_model parameters. Skipping.")
    exit(0)

# Add import statement after pydantic import
import_addition = """
from api.models import (
    HealthResponse,
    FullHealthResponse,
    IBConnectionTestResponse,
    IBConnectResponse,
    SafetyStatusResponse,
    CircuitBreakerStatus,
    SafetyConfigResponse,
    KillSwitchToggleResponse,
    TechnicalAnalysisResponse,
    BarsResponse,
    RedditSentimentResponse,
    NewsSentimentResponse,
    PortfolioResponse,
    PaperPositionsResponse,
    PaperTradeResponse,
    PaperPerformanceResponse,
    PendingSignalsResponse,
    PaperKillSwitchStatus,
    PaperKillSwitchToggleResponse,
    ResetSignalsResponse,
    TradeHistoryResponse,
    DailyPnLResponse,
    DecisionHistoryResponse,
    StatsSummaryResponse,
    DrawdownResponse,
    WebSocketStatusResponse,
)
"""

# Add after pydantic import
if "from pydantic import BaseModel" in content:
    content = content.replace(
        "from pydantic import BaseModel",
        "from pydantic import BaseModel\n" + import_addition
    )
    print("✅ Added API models import")

# Also ensure APIRouter is imported
if "from fastapi import FastAPI, HTTPException, Depends, Request" in content:
    content = content.replace(
        "from fastapi import FastAPI, HTTPException, Depends, Request",
        "from fastapi import FastAPI, HTTPException, Depends, Request, APIRouter"
    )
    print("✅ Updated FastAPI import to include APIRouter")

# Dictionary of endpoint decorators and response models
replacements = {
    '@app.get("/health")': '@app.get("/health", response_model=HealthResponse)',
    '@app.get("/health/full")': '@app.get("/health/full", response_model=FullHealthResponse)',
    '@app.get("/ib/connection-test")': '@app.get("/ib/connection-test", response_model=IBConnectionTestResponse)',
    '@app.post("/ib/connect")': '@app.post("/ib/connect", response_model=IBConnectResponse)',
    '@app.post("/safety/kill-switch/activate")': '@app.post("/safety/kill-switch/activate", response_model=KillSwitchToggleResponse)',
    '@app.post("/safety/kill-switch/deactivate")': '@app.post("/safety/kill-switch/deactivate", response_model=KillSwitchToggleResponse)',
    '@app.get("/safety/status")': '@app.get("/safety/status", response_model=SafetyStatusResponse)',
    '@app.get("/safety/circuit-breakers")': '@app.get("/safety/circuit-breakers", response_model=CircuitBreakerStatus)',
    '@app.get("/safety/config")': '@app.get("/safety/config", response_model=SafetyConfigResponse)',
    '@app.post("/analyze/technical")': '@app.post("/analyze/technical", response_model=TechnicalAnalysisResponse)',
    '@app.get("/analyze/bars/{symbol}")': '@app.get("/analyze/bars/{symbol}", response_model=BarsResponse)',
    '@app.get("/sentiment/reddit")': '@app.get("/sentiment/reddit", response_model=RedditSentimentResponse)',
    '@app.get("/sentiment/news/{symbol}")': '@app.get("/sentiment/news/{symbol}", response_model=NewsSentimentResponse)',
    '@app.get("/portfolio")': '@app.get("/portfolio", response_model=PortfolioResponse)',
    '@app.get("/portfolio/paper/positions")': '@app.get("/portfolio/paper/positions", response_model=PaperPositionsResponse)',
    '@app.post("/portfolio/paper/trade")': '@app.post("/portfolio/paper/trade", response_model=PaperTradeResponse)',
    '@app.get("/portfolio/paper/performance")': '@app.get("/portfolio/paper/performance", response_model=PaperPerformanceResponse)',
    '@app.get("/paper/pending-signals")': '@app.get("/paper/pending-signals", response_model=PendingSignalsResponse)',
    '@app.get("/paper/kill-switch")': '@app.get("/paper/kill-switch", response_model=PaperKillSwitchStatus)',
    '@app.post("/paper/kill-switch")': '@app.post("/paper/kill-switch", response_model=PaperKillSwitchToggleResponse)',
    '@app.post("/paper/reset-pending-signals")': '@app.post("/paper/reset-pending-signals", response_model=ResetSignalsResponse)',
    '@app.get("/portfolio/history/trades")': '@app.get("/portfolio/history/trades", response_model=TradeHistoryResponse)',
    '@app.get("/portfolio/history/daily-pnl")': '@app.get("/portfolio/history/daily-pnl", response_model=DailyPnLResponse)',
    '@app.get("/portfolio/history/decisions")': '@app.get("/portfolio/history/decisions", response_model=DecisionHistoryResponse)',
    '@app.get("/portfolio/stats/summary")': '@app.get("/portfolio/stats/summary", response_model=StatsSummaryResponse)',
    '@app.get("/portfolio/stats/drawdown")': '@app.get("/portfolio/stats/drawdown", response_model=DrawdownResponse)',
    '@app.get("/ws/status")': '@app.get("/ws/status", response_model=WebSocketStatusResponse)',
}

count = 0
for old, new in replacements.items():
    if old in content:
        content = content.replace(old, new)
        count += 1

print(f"✅ Added response_model to {count} endpoints")

# Add v1 router setup
if "v1_router = APIRouter" not in content:
    # Find where app is created
    if "app = FastAPI(" in content:
        # Find the lifespan context manager
        lifespan_pos = content.find("@asynccontextmanager\nasync def lifespan(app: FastAPI):")
        if lifespan_pos > 0:
            # Insert before lifespan
            v1_setup = '''
# ── API Versioning ────────────────────────────────────────────────────────────
# Create v1 router with /v1 prefix for future versioning support
v1_router = APIRouter(prefix="/v1", tags=["v1"])

'''
            content = content[:lifespan_pos] + v1_setup + content[lifespan_pos:]
            print("✅ Added v1_router setup")

# Add router include after other routers
if "app.include_router(v1_router)" not in content:
    # Find where other routers are included
    if "app.include_router(journal_router" in content:
        # Find the line and add after it
        include_pos = content.find("app.include_router(journal_router")
        if include_pos > 0:
            # Find the end of the line
            line_end = content.find("\n", include_pos)
            # Insert the v1 router include
            content = content[:line_end + 1] + 'app.include_router(v1_router)\n' + content[line_end + 1:]
            print("✅ Registered v1_router")

# Write back
main_file.write_text(content)
print("\n✅ Successfully updated main.py with all response models!")
print("✅ main.py is ready to use")
