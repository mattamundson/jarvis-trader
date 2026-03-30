#!/usr/bin/env python3
"""
Script to add response_model parameters to all API endpoints in main.py
and create API versioning with v1 router.
"""

import re
from pathlib import Path

# Read the file
main_file = Path("main.py")
content = main_file.read_text()

# First, add the API models import after the pydantic import
import_section_pattern = r"(from pydantic import BaseModel\n)"
new_import = r"""\1
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
content = re.sub(import_section_pattern, new_import, content)

# Also update FastAPI import to include APIRouter
content = content.replace(
    "from fastapi import FastAPI, HTTPException, Depends, Request",
    "from fastapi import FastAPI, HTTPException, Depends, Request, APIRouter",
)

# Add response_model to @app.get("/health")
content = content.replace(
    '@app.get("/health")', '@app.get("/health", response_model=HealthResponse)'
)

# Add response_model to @app.get("/health/full")
content = content.replace(
    '@app.get("/health/full")', '@app.get("/health/full", response_model=FullHealthResponse)'
)

# Add response_model to @app.get("/ib/connection-test")
content = content.replace(
    '@app.get("/ib/connection-test")',
    '@app.get("/ib/connection-test", response_model=IBConnectionTestResponse)',
)

# Add response_model to @app.post("/ib/connect")
content = content.replace(
    '@app.post("/ib/connect")', '@app.post("/ib/connect", response_model=IBConnectResponse)'
)

# Add response_model to @app.post("/safety/kill-switch/activate")
content = content.replace(
    '@app.post("/safety/kill-switch/activate")',
    '@app.post("/safety/kill-switch/activate", response_model=KillSwitchToggleResponse)',
)

# Add response_model to @app.post("/safety/kill-switch/deactivate")
content = content.replace(
    '@app.post("/safety/kill-switch/deactivate")',
    '@app.post("/safety/kill-switch/deactivate", response_model=KillSwitchToggleResponse)',
)

# Add response_model to @app.get("/safety/status")
content = content.replace(
    '@app.get("/safety/status")', '@app.get("/safety/status", response_model=SafetyStatusResponse)'
)

# Add response_model to @app.get("/safety/circuit-breakers")
content = content.replace(
    '@app.get("/safety/circuit-breakers")',
    '@app.get("/safety/circuit-breakers", response_model=CircuitBreakerStatus)',
)

# Add response_model to @app.get("/safety/config")
content = content.replace(
    '@app.get("/safety/config")', '@app.get("/safety/config", response_model=SafetyConfigResponse)'
)

# Add response_model to @app.post("/safety/reset-daily-pnl")
content = content.replace(
    '@app.post("/safety/reset-daily-pnl")',
    '@app.post("/safety/reset-daily-pnl", response_model=dict)',
)

# Add response_model to @app.post("/analyze/technical")
content = content.replace(
    '@app.post("/analyze/technical")',
    '@app.post("/analyze/technical", response_model=TechnicalAnalysisResponse)',
)

# Add response_model to @app.get("/analyze/bars/{symbol}")
content = content.replace(
    '@app.get("/analyze/bars/{symbol}")',
    '@app.get("/analyze/bars/{symbol}", response_model=BarsResponse)',
)

# Add response_model to @app.get("/sentiment/reddit")
content = content.replace(
    '@app.get("/sentiment/reddit")',
    '@app.get("/sentiment/reddit", response_model=RedditSentimentResponse)',
)

# Add response_model to @app.get("/sentiment/news/{symbol}")
content = content.replace(
    '@app.get("/sentiment/news/{symbol}")',
    '@app.get("/sentiment/news/{symbol}", response_model=NewsSentimentResponse)',
)

# Add response_model to @app.get("/portfolio")
content = content.replace(
    '@app.get("/portfolio")', '@app.get("/portfolio", response_model=PortfolioResponse)'
)

# Add response_model to @app.get("/portfolio/paper/positions")
content = content.replace(
    '@app.get("/portfolio/paper/positions")',
    '@app.get("/portfolio/paper/positions", response_model=PaperPositionsResponse)',
)

# Add response_model to @app.post("/portfolio/paper/trade")
content = content.replace(
    '@app.post("/portfolio/paper/trade")',
    '@app.post("/portfolio/paper/trade", response_model=PaperTradeResponse)',
)

# Add response_model to @app.get("/portfolio/paper/performance")
content = content.replace(
    '@app.get("/portfolio/paper/performance")',
    '@app.get("/portfolio/paper/performance", response_model=PaperPerformanceResponse)',
)

# Add response_model to @app.get("/paper/pending-signals")
content = content.replace(
    '@app.get("/paper/pending-signals")',
    '@app.get("/paper/pending-signals", response_model=PendingSignalsResponse)',
)

# Add response_model to @app.get("/paper/kill-switch")
content = content.replace(
    '@app.get("/paper/kill-switch")',
    '@app.get("/paper/kill-switch", response_model=PaperKillSwitchStatus)',
)

# Add response_model to @app.post("/paper/kill-switch")
content = content.replace(
    '@app.post("/paper/kill-switch")',
    '@app.post("/paper/kill-switch", response_model=PaperKillSwitchToggleResponse)',
)

# Add response_model to @app.post("/paper/reset-pending-signals")
content = content.replace(
    '@app.post("/paper/reset-pending-signals")',
    '@app.post("/paper/reset-pending-signals", response_model=ResetSignalsResponse)',
)

# Add response_model to @app.get("/portfolio/history/trades")
content = content.replace(
    '@app.get("/portfolio/history/trades")',
    '@app.get("/portfolio/history/trades", response_model=TradeHistoryResponse)',
)

# Add response_model to @app.get("/portfolio/history/daily-pnl")
content = content.replace(
    '@app.get("/portfolio/history/daily-pnl")',
    '@app.get("/portfolio/history/daily-pnl", response_model=DailyPnLResponse)',
)

# Add response_model to @app.get("/portfolio/history/decisions")
content = content.replace(
    '@app.get("/portfolio/history/decisions")',
    '@app.get("/portfolio/history/decisions", response_model=DecisionHistoryResponse)',
)

# Add response_model to @app.get("/portfolio/stats/summary")
content = content.replace(
    '@app.get("/portfolio/stats/summary")',
    '@app.get("/portfolio/stats/summary", response_model=StatsSummaryResponse)',
)

# Add response_model to @app.get("/portfolio/stats/drawdown")
content = content.replace(
    '@app.get("/portfolio/stats/drawdown")',
    '@app.get("/portfolio/stats/drawdown", response_model=DrawdownResponse)',
)

# Add response_model to @app.get("/ws/status")
content = content.replace(
    '@app.get("/ws/status")', '@app.get("/ws/status", response_model=WebSocketStatusResponse)'
)

# Write the updated content
main_file.write_text(content)
print("✅ Successfully updated main.py with response_model parameters!")
