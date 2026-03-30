# JARVIS TRADER — Pydantic Response Models Documentation

## Overview

This document describes the complete implementation of Pydantic v2 response models for the JARVIS TRADER API. All 30+ endpoints now have strongly-typed response models, enabling:

- **Automatic request/response validation** at runtime
- **OpenAPI/Swagger schema generation** for interactive documentation
- **Type hints** for client code generation
- **IDE autocomplete** support for API responses

## Implementation Summary

### Files Created

1. **`api/models.py`** (25 KB)
   - Contains 30+ Pydantic v2 models
   - Organized into logical sections (Health, Safety, Analysis, Portfolio, etc.)
   - Full docstrings and Field descriptions

2. **`api/__init__.py`** (2.3 KB)
   - Exports all models for clean imports
   - Provides a single entry point: `from api.models import *`

### Files Modified

1. **`main.py`**
   - Added import for all API response models
   - Added `response_model=` parameter to all @app.get() and @app.post() decorators
   - Created APIRouter with `/v1` prefix for API versioning
   - Backward compatible: all routes available at both `/` and `/v1/`

## Model Organization

### 1. Enum Types

```python
StatusEnum          # ok, degraded, error, healthy, kill_switch_active, circuit_breaker_tripped
HealthStatusEnum    # healthy, degraded, error, etc.
SignalEnum          # buy, sell, hold, neutral, bullish, bearish
OrderActionEnum     # buy, sell, sell_short, buy_to_cover
```

### 2. Health Check Models

#### HealthResponse
Basic health check endpoint response.
```python
{
  "status": "ok",
  "version": "1.2.0",
  "timestamp": "2026-03-29T...",
  "live_trading": false,
  "kill_switch_active": false,
  "paper_mode": true,
  "database": "connected",
  "ibkr_connected": false,
  "schwab_connected": false,
  "uptime_seconds": 3600.5,
  "paper_trading": {
    "paper_kill_switch": false,
    "safety_kill_switch": false,
    "open_positions": 5,
    "scheduler_running": true,
    "scheduler_jobs": ["daily_scan", "eod_close"]
  },
  "cache": {
    "data_files": 42,
    "results_files": 8
  }
}
```

#### FullHealthResponse
Comprehensive health check with subsystem status.
```python
{
  "overall": "healthy",
  "timestamp": "2026-03-29T...",
  "uptime_seconds": 3600.5,
  "version": "1.1.0",
  "phase": "paper_trading",
  "subsystems": {
    "database": { "status": "ok", "details": {...} },
    "safety_layer": { "status": "ok", "kill_switch_active": false },
    "ib_gateway": { "status": "error", "error": "..." },
    "circuit_breakers": { "status": "ok", "all_clear": true },
    "portfolio": { "status": "ok", "open_positions": 5 },
    "pnl_monitor": { "status": "ok", "daily_pnl": 1234.56 }
  }
}
```

### 3. IB Gateway Models

#### IBConnectionTestResponse
Connection test result.
```python
{
  "connected": true,
  "gateway_version": "9.76",
  "server": "ibkr.example.com:4001",
  "client_id": 123,
  "latency_ms": 45.5
}
```

#### IBConnectResponse
Connection attempt response.
```python
{
  "status": "connected",
  "message": "Successfully connected to IB Gateway",
  "connected": true
}
```

### 4. Safety & Risk Management Models

#### SafetyStatusResponse
Current safety layer state.
```python
{
  "kill_switch_active": false,
  "kill_switch_reason": null,
  "daily_pnl": 1234.56,
  "daily_limit": -5000.00,
  "daily_pnl_pct": 0.0245,
  "daily_limit_pct": -0.10,
  "daily_limit_breached": false,
  "drawdown_pct": -0.05,
  "drawdown_limit_pct": -0.20,
  "drawdown_breached": false,
  "portfolio_equity": 50234.56,
  "starting_balance": 50000.00,
  "pnl_source": "sqlite",
  "current_balance": 50234.56
}
```

#### CircuitBreakerStatus
Detailed circuit breaker snapshot.
```python
{
  "daily_pnl": 1234.56,
  "daily_limit": -5000.00,
  "daily_pnl_pct": 0.0245,
  "daily_limit_pct": -0.10,
  "daily_limit_breached": false,
  "drawdown_pct": -0.05,
  "drawdown_limit_pct": -0.20,
  "drawdown_breached": false,
  "kill_switch_active": false,
  "kill_switch_reason": null,
  "pnl_source": "sqlite",
  "current_balance": 50234.56,
  "starting_balance": 50000.00,
  "orders_last_minute": 2,
  "all_clear": true
}
```

#### SafetyConfigResponse
Risk configuration (read-only).
```python
{
  "max_daily_loss_pct": -0.10,
  "max_drawdown_pct": -0.20,
  "max_orders_per_minute": 30,
  "min_order_size": 1.0
}
```

#### KillSwitchToggleResponse
Kill switch activation/deactivation result.
```python
{
  "status": "kill_switch_activated",
  "reason": "manual",
  "activated_at": "2026-03-29T15:30:00"
}
```

### 5. Analysis Models

#### TechnicalAnalysisResponse
Technical analysis results.
```python
{
  "symbol": "SPY",
  "timestamp": "2026-03-29T15:30:00",
  "timeframe": "5m",
  "signal": "buy",
  "confidence": 0.78,
  "trend": "uptrend",
  "regime": "trending",
  "is_overbought": false,
  "is_oversold": false,
  "summary": "Bullish momentum with support at 445.50",
  "reasoning": "Detailed technical reasoning from agent...",
  "scores": {
    "trend": 0.85,
    "momentum": 0.72,
    "volatility": 0.45,
    "volume": 0.65
  },
  "levels": {
    "current_price": 447.82,
    "support": [445.50, 443.20],
    "resistance": [450.00, 452.50]
  },
  "raw_indicators": {
    "rsi": 62,
    "macd": {"line": 0.45, "signal": 0.38},
    "bb_position": 0.72
  }
}
```

#### BarsResponse
Historical OHLCV data.
```python
{
  "symbol": "SPY",
  "timeframe": "5m",
  "bars": [
    {"timestamp": "...", "open": 447.50, "high": 448.20, "low": 447.10, "close": 447.82, "volume": 1250000},
    ...
  ],
  "count": 200
}
```

#### RedditSentimentResponse
Reddit trending tickers.
```python
{
  "filter": "all-stocks",
  "tickers": ["NVDA", "TSLA", "SPY", "QQQ", ...]
}
```

#### NewsSentimentResponse
News sentiment via Finnhub.
```python
{
  "symbol": "SPY",
  "sentiment": {
    "buzz": 0.85,
    "sentiment": 0.62,
    "articles": 450
  }
}
```

### 6. Portfolio Models

#### PortfolioResponse
Current portfolio state.
```python
{
  "total_equity": 55234.56,
  "cash_balance": 10234.56,
  "unrealized_pnl": 2000.00,
  "realized_pnl": 500.00,
  "daily_pnl": 1234.56,
  "margin_used": 20000.00,
  "margin_available": 30000.00,
  "positions": [
    {
      "symbol": "SPY",
      "quantity": 100,
      "average_price": 445.50,
      "current_price": 447.82,
      "unrealized_pnl": 232.00
    }
  ]
}
```

### 7. Paper Trading Models

#### PaperPositionsResponse
Open paper trading positions.
```python
{
  "positions": [
    {
      "trade_id": "TR-20260329-001",
      "symbol": "SPY",
      "action": "buy",
      "quantity": 100,
      "entry_price": 445.50,
      "entry_time": "2026-03-29T10:30:00",
      "notes": "Technical breakout signal"
    }
  ],
  "count": 1
}
```

#### PaperTradeResponse
Trade submission result.
```python
{
  "status": "opened",
  "trade_id": "TR-20260329-001",
  "symbol": "SPY",
  "action": "buy",
  "quantity": 100,
  "entry_price": 445.50
}
```

#### PaperPerformanceResponse
Paper trading performance metrics.
```python
{
  "performance": {
    "total_trades": 45,
    "closed_trades": 38,
    "open_trades": 7,
    "total_pnl": 3456.78,
    "win_rate": 0.632,
    "avg_win": 150.50,
    "avg_loss": -85.25
  }
}
```

### 8. Pending Signals Models

#### PendingSignalsResponse
Signals from daily scanner.
```python
{
  "signals": [
    {
      "date": "2026-03-29",
      "symbol": "TSLA",
      "direction": "long",
      "entry_price": 195.50,
      "stop": 190.00,
      "target": 210.00,
      "regime": "trending",
      "status": "pending"
    }
  ],
  "count": 5
}
```

### 9. Kill Switch Control Models

#### PaperKillSwitchStatus
Paper trading kill switch state.
```python
{
  "active": false,
  "reason": null,
  "activated_at": null
}
```

#### PaperKillSwitchToggleResponse
Kill switch toggle result.
```python
{
  "status": "kill_switch_activated",
  "reason": "max_daily_loss_exceeded",
  "activated_at": "2026-03-29T15:30:00"
}
```

#### ResetSignalsResponse
Pending signals reset result.
```python
{
  "status": "cleared",
  "signals_cleared": 5
}
```

### 10. Historical Data Models

#### TradeHistoryResponse
Historical trades.
```python
{
  "trades": [
    {
      "trade_id": "TR-20260329-001",
      "symbol": "SPY",
      "action": "buy",
      "quantity": 100,
      "entry_price": 445.50,
      "exit_price": 447.82,
      "entry_time": "2026-03-29T10:30:00",
      "exit_time": "2026-03-29T14:45:00",
      "pnl": 232.00,
      "status": "closed"
    }
  ],
  "count": 38
}
```

#### DailyPnLResponse
Daily P&L history.
```python
{
  "daily_pnl": [
    {
      "date": "2026-03-29",
      "daily_pnl": 1234.56,
      "cumulative_pnl": 5678.90,
      "trades_count": 8,
      "starting_balance": 50000.00,
      "ending_balance": 51234.56
    }
  ],
  "days": 30,
  "count": 28
}
```

#### DecisionHistoryResponse
Agent decisions.
```python
{
  "decisions": [
    {
      "decision_id": "DEC-20260329-001",
      "symbol": "SPY",
      "agent": "technical_analyst",
      "action": "buy",
      "confidence": 0.78,
      "reasoning": "Bullish breakout on 5-minute chart",
      "timestamp": "2026-03-29T10:30:00"
    }
  ],
  "count": 45
}
```

#### StatsSummaryResponse
Performance statistics.
```python
{
  "total_trades": 45,
  "winning_trades": 28,
  "losing_trades": 17,
  "win_rate": 0.622,
  "total_pnl": 3456.78,
  "avg_win": 150.50,
  "avg_loss": -85.25,
  "profit_factor": 2.15,
  "best_trade": 450.00,
  "worst_trade": -250.00
}
```

#### DrawdownResponse
Drawdown metrics.
```python
{
  "current_drawdown_pct": -0.05,
  "max_drawdown_pct": -0.12,
  "peak_equity": 52000.00,
  "current_equity": 49400.00
}
```

### 11. WebSocket Models

#### WebSocketStatusResponse
WebSocket manager status.
```python
{
  "manager_active": true,
  "connected_clients": 3,
  "clients": [
    {
      "client_id": "ws-001",
      "connected_at": "2026-03-29T10:00:00",
      "event_types_subscribed": ["order_fill", "kill_switch"]
    }
  ],
  "events_sent_total": 15234,
  "events_sent_last_hour": 234
}
```

## API Endpoints with Response Models

| Endpoint | Method | Response Model | Purpose |
|----------|--------|-----------------|---------|
| `/health` | GET | HealthResponse | Basic health check |
| `/health/full` | GET | FullHealthResponse | Comprehensive health check |
| `/ib/connection-test` | GET | IBConnectionTestResponse | Test IB Gateway connection |
| `/ib/connect` | POST | IBConnectResponse | Connect to IB Gateway |
| `/safety/status` | GET | SafetyStatusResponse | Safety layer status |
| `/safety/circuit-breakers` | GET | CircuitBreakerStatus | Circuit breaker state |
| `/safety/config` | GET | SafetyConfigResponse | Risk configuration |
| `/safety/kill-switch/activate` | POST | KillSwitchToggleResponse | Activate kill switch |
| `/safety/kill-switch/deactivate` | POST | KillSwitchToggleResponse | Deactivate kill switch |
| `/analyze/technical` | POST | TechnicalAnalysisResponse | Run technical analysis |
| `/analyze/bars/{symbol}` | GET | BarsResponse | Get OHLCV bars |
| `/sentiment/reddit` | GET | RedditSentimentResponse | Reddit sentiment |
| `/sentiment/news/{symbol}` | GET | NewsSentimentResponse | News sentiment |
| `/portfolio` | GET | PortfolioResponse | Portfolio state |
| `/portfolio/paper/positions` | GET | PaperPositionsResponse | Paper positions |
| `/portfolio/paper/trade` | POST | PaperTradeResponse | Submit paper trade |
| `/portfolio/paper/performance` | GET | PaperPerformanceResponse | Paper performance |
| `/paper/pending-signals` | GET | PendingSignalsResponse | Pending signals |
| `/paper/kill-switch` | GET | PaperKillSwitchStatus | Paper kill switch |
| `/paper/kill-switch` | POST | PaperKillSwitchToggleResponse | Toggle paper kill switch |
| `/paper/reset-pending-signals` | POST | ResetSignalsResponse | Clear pending signals |
| `/portfolio/history/trades` | GET | TradeHistoryResponse | Trade history |
| `/portfolio/history/daily-pnl` | GET | DailyPnLResponse | Daily P&L history |
| `/portfolio/history/decisions` | GET | DecisionHistoryResponse | Decision history |
| `/portfolio/stats/summary` | GET | StatsSummaryResponse | Performance stats |
| `/portfolio/stats/drawdown` | GET | DrawdownResponse | Drawdown metrics |
| `/ws/status` | GET | WebSocketStatusResponse | WebSocket status |

## API Versioning

The API now supports versioning via the `/v1` prefix:

### Backward Compatibility
All endpoints are available at:
- **Legacy routes**: `GET /health`, `POST /safety/kill-switch/activate`, etc.
- **Versioned routes**: `GET /v1/health`, `POST /v1/safety/kill-switch/activate`, etc.

### Future Proofing
To add a new API version:

1. Create `v2_router = APIRouter(prefix="/v2", tags=["v2"])`
2. Register it: `app.include_router(v2_router)`
3. Implement new endpoints or modified versions
4. Legacy endpoints remain unchanged

## OpenAPI/Swagger Integration

The response models automatically generate OpenAPI schemas:

1. **Interactive documentation**: Visit `http://localhost:8010/docs`
2. **ReDoc**: Visit `http://localhost:8010/redoc`
3. **OpenAPI JSON**: Visit `http://localhost:8010/openapi.json`

All response models appear in the schema with:
- Full field descriptions
- Type information
- Example values
- Required/optional indicators

## Client Generation

The OpenAPI schema can be used to generate typed client libraries:

```bash
# Generate Python client
openapi-python-client generate --url http://localhost:8010/openapi.json

# Generate TypeScript client
openapi-typescript-codegen generate --url http://localhost:8010/openapi.json

# Generate Go client
oapi-codegen -package=jarvistrader http://localhost:8010/openapi.json > client.go
```

## Using Response Models in Code

### Basic Usage

```python
from api.models import HealthResponse, SafetyStatusResponse

# In an endpoint
@app.get("/custom/endpoint", response_model=HealthResponse)
async def custom_endpoint():
    return {
        "status": "ok",
        "version": "1.2.0",
        # ... other fields
    }
```

### Type Checking

```python
from api.models import PortfolioResponse

def process_portfolio(portfolio: PortfolioResponse):
    # IDE provides autocomplete for all fields
    equity = portfolio.total_equity
    for position in portfolio.positions:
        symbol = position.symbol
        quantity = position.quantity
```

### Creating Instances

```python
from api.models import Position, PortfolioResponse

position = Position(
    symbol="SPY",
    quantity=100,
    average_price=445.50,
    current_price=447.82,
    unrealized_pnl=232.00
)

portfolio = PortfolioResponse(
    total_equity=55234.56,
    cash_balance=10234.56,
    unrealized_pnl=2000.00,
    realized_pnl=500.00,
    daily_pnl=1234.56,
    margin_used=20000.00,
    margin_available=30000.00,
    positions=[position]
)
```

## Validation Features

All models include validation:

```python
# Type validation
portfolio = PortfolioResponse(
    total_equity="not a number",  # ❌ ValidationError
)

# Enum validation
from api.models import SignalEnum
signal = SignalEnum("invalid")  # ❌ ValidationError

# Required field validation
health = HealthResponse(status="ok")  # ❌ ValidationError (missing required fields)

# Constraint validation
analysis = TechnicalAnalysisResponse(
    confidence=1.5,  # ❌ ValidationError (must be 0-1)
)
```

## Migration Guide

### For Existing Clients

No breaking changes! All existing endpoints continue to work exactly as before:

```bash
# Old endpoint URLs still work
curl http://localhost:8010/health

# New versioned URLs also work
curl http://localhost:8010/v1/health
```

### For New Clients

Use the typed response models:

```python
import httpx
from api.models import HealthResponse

async with httpx.AsyncClient() as client:
    response = await client.get("http://localhost:8010/v1/health")
    health: HealthResponse = HealthResponse(**response.json())
    print(f"Status: {health.status}")
```

## Benefits

1. **Type Safety**: Catch response mismatches at runtime
2. **API Documentation**: Auto-generated OpenAPI/Swagger docs
3. **Client Generation**: Automatically generate typed clients
4. **IDE Support**: Full autocomplete and type hints
5. **Validation**: Automatic response validation
6. **Backward Compatibility**: Gradual migration path
7. **Versioning**: Easy to add new API versions

## Files

- `/sessions/blissful-stoic-curie/mnt/jarvis-trader/engine/api/__init__.py` — Model exports
- `/sessions/blissful-stoic-curie/mnt/jarvis-trader/engine/api/models.py` — All Pydantic models
- `/sessions/blissful-stoic-curie/mnt/jarvis-trader/engine/main.py` — Updated with response_model parameters
