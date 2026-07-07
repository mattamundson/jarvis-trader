# PostgreSQL Persistent Trade Logging for JARVIS TRADER

## Overview

JARVIS TRADER now has full PostgreSQL integration for persistent audit trails of all trading activity. The system logs:

- **Orders**: Every order submitted, filled, rejected (with provenance)
- **Agent Decisions**: Complete reasoning from all 10 agents (technical, news, social, fundamental, debate, trader, risk, fund)
- **Portfolio Snapshots**: Account state captured every 30 minutes
- **Safety Events**: Kill switch activations, circuit breaker triggers, order rejections
- **Performance Metrics**: Daily P&L, win rate, Sharpe ratio

All logging is **graceful and non-blocking** — if PostgreSQL is unavailable, the trading engine continues to operate in degraded mode.

---

## Installation

### 1. Install PostgreSQL (if not already installed)

```bash
# macOS
brew install postgresql

# Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib

# Windows
# Download from https://www.postgresql.org/download/windows/
```

### 2. Create the database

```bash
# Connect as postgres user
psql -U postgres

# Inside psql:
CREATE DATABASE jarvis_trader;
CREATE USER jarvis WITH PASSWORD 'jarvis';
ALTER ROLE jarvis CREATEDB;
GRANT ALL PRIVILEGES ON DATABASE jarvis_trader TO jarvis;
\q
```

### 3. Initialize the schema

```bash
# Run the init script from Docker or manually
psql -U jarvis -d jarvis_trader -f infrastructure/postgres/init.sql
```

### 4. Install Python dependencies

```bash
cd engine
pip install -r requirements-core.txt
```

This installs `asyncpg==0.31.0` for async PostgreSQL support.

---

## Files Added/Modified

### New Files

#### `engine/database/connection.py`
- **Async connection pool manager** using `asyncpg`
- Min/max pool size: 2/10 connections
- Graceful fallback if Postgres unavailable
- Exports: `init_pool()`, `close_pool()`, `get_pool()`, `execute()`, `execute_one()`, `execute_insert()`, `execute_many()`

**Key Features:**
- All functions return `None` if pool unavailable (never crash)
- Command timeout: 10 seconds per query
- Connection statement caching for performance

#### `engine/database/repository.py`
- **High-level CRUD operations** for all audit tables
- Async functions for inserting and querying data

**Functions:**
```python
# Insert operations
await insert_order(order_data: dict) → order_id
await insert_decision(agent_name, symbol, signal, confidence, reasoning, ...) → decision_id
await insert_portfolio_snapshot(equity, cash, margin_used, positions_json, ...) → snapshot_id
await insert_safety_event(event_type, details, reason) → event_id
await insert_alert(level, title, body, source) → alert_id

# Query operations
await get_recent_orders(symbol=None, limit=50) → [dicts]
await get_recent_decisions(agent_name=None, symbol=None, limit=50) → [dicts]
await get_daily_pnl(date: str) → dict
await get_portfolio_snapshots(limit=10) → [dicts]
await get_safety_events(resolved=False, limit=50) → [dicts]
```

---

## Integration Points

### 1. **main.py (lifespan management)**

```python
# Startup
await init_pool()

# Shutdown
await close_pool()

# Portfolio snapshot job (every 30 min, 9:30am-4:30pm CT weekdays)
async def snapshot_portfolio_for_postgres():
    await repository.insert_portfolio_snapshot(...)
```

**Behavior:** Pool initialization is logged but non-blocking. If Postgres unavailable, logs warning and continues.

### 2. **agents/pipeline.py (agent decisions)**

```python
# After pipeline completion
await self._log_pipeline_to_postgres(symbol, pipeline_result, trade_decision, errors)
```

**What gets logged:**
- Technical analyst decision (signal, confidence, indicators)
- News analyst decision
- Social analyst decision
- Fundamental analyst decision
- Debate result (bull vs bear verdict)
- Trader decision (main synthesis)
- Risk manager decision (approved/rejected, risk score)
- Fund manager decision (final conviction, quantity)

**Provenance:** Each decision includes:
- Full LLM reasoning text
- Signal value (-1.0 to 1.0)
- Confidence (0.0 to 1.0)
- Model used, token count, latency

### 3. **execution/order_router.py (order logging)**

```python
# After each order submission attempt
await self._log_order_result(order, result, is_futures, is_options)
```

**What gets logged:**
- Symbol, quantity, order type
- Limit price, stop price
- Instrument type (futures/options)
- Status (pending, filled, rejected, error)
- Broker (IBKR, Schwab)
- Broker order ID
- Commission, P&L, notes

**Coverage:** All three routing paths:
1. Futures → IBKR
2. Options → Schwab
3. Equity → Schwab (with IBKR fallback)

### 4. **risk/safety_layer.py (safety events)**

```python
# Kill switch activation
asyncio.create_task(self._log_safety_event(
    "kill_switch_activate",
    reason.value,
    {"reason": reason.value, "message": message}
))

# Kill switch deactivation
asyncio.create_task(self._log_safety_event(
    "kill_switch_deactivate",
    f"Deactivated by {authorized_by}",
    {"authorized_by": authorized_by, "resolved": True}
))
```

**What gets logged:**
- Event type (kill_switch_activate, kill_switch_deactivate, order_rejected, etc.)
- Reason (human-readable)
- Details (JSON dict with context)
- Resolved status and timestamp

---

## Configuration

### Environment Variables

Add to `.env`:

```bash
# PostgreSQL connection string
POSTGRES_URL=postgresql://jarvis:jarvis@localhost:5432/jarvis_trader
```

### Default Settings

- **Host:** localhost
- **Port:** 5432
- **Database:** jarvis_trader
- **User:** jarvis
- **Password:** jarvis

---

## Database Schema

All tables defined in `infrastructure/postgres/init.sql`:

### orders
- id (BIGSERIAL PRIMARY KEY)
- created_at (TIMESTAMPTZ)
- symbol (VARCHAR)
- quantity (INTEGER)
- order_type (VARCHAR)
- is_futures, is_options (BOOLEAN)
- status (VARCHAR) — pending, filled, rejected, cancelled
- fill_price, fill_quantity, commission, pnl (DECIMAL)
- triggered_by, signal_score, approved_by (VARCHAR)
- Indexes: symbol, created_at, status

### agent_decisions
- id (BIGSERIAL PRIMARY KEY)
- created_at (TIMESTAMPTZ)
- agent_name (VARCHAR) — technical, news, social, fundamental, trader, etc.
- symbol (VARCHAR)
- signal, confidence (DECIMAL -1.0 to 1.0)
- reasoning (TEXT) — full LLM output
- indicators (JSONB) — raw indicator values
- model_used, tokens_used, latency_ms (VARCHAR/INTEGER)
- order_id (BIGINT FK) — link to related order
- Indexes: agent_name, symbol, created_at

### portfolio_snapshots
- id (BIGSERIAL PRIMARY KEY)
- captured_at (TIMESTAMPTZ)
- source (VARCHAR) — ibkr, schwab, paper
- total_equity, cash_balance, unrealized_pnl, realized_pnl (DECIMAL)
- daily_pnl, margin_used, margin_available (DECIMAL)
- positions (JSONB) — array of {symbol, qty, avg_cost, mkt_value, pnl}
- Index: captured_at

### safety_events
- id (BIGSERIAL PRIMARY KEY)
- created_at (TIMESTAMPTZ)
- event_type (VARCHAR) — kill_switch_activate, order_rejected, etc.
- reason (VARCHAR)
- details (JSONB) — context and details
- resolved (BOOLEAN)
- resolved_at, resolved_by (TIMESTAMPTZ, VARCHAR)

### alerts
- id (BIGSERIAL PRIMARY KEY)
- created_at (TIMESTAMPTZ)
- level (VARCHAR) — info, warning, critical
- title (VARCHAR)
- body (TEXT)
- source (VARCHAR)
- acknowledged (BOOLEAN)

### performance_daily
- trade_date (DATE PRIMARY KEY)
- total_trades, winning_trades, losing_trades (INTEGER)
- gross_pnl, net_pnl, commissions (DECIMAL)
- max_drawdown (DECIMAL)
- sharpe_ratio (DECIMAL)
- equity_eod (DECIMAL)

---

## Error Handling & Degradation

### If PostgreSQL is unavailable:

1. **Connection Phase**
   - Logs warning: "PostgreSQL server not available (will retry)"
   - `init_pool()` returns `None`
   - System continues with SQLite only

2. **Query Phase**
   - All queries check `if pool is None` and return gracefully
   - Insert operations return `None` and log debug message
   - Trading never blocked by database errors

3. **Timeout**
   - 10-second command timeout per query
   - Timeouts logged, operation continues
   - No retry loop (avoid cascade failures)

### Reconnection Strategy

Currently **no automatic reconnection** is implemented. In production, you would:
- Monitor `/health` endpoint for pool status
- Implement periodic reconnection attempts in a background task
- Alert ops team if pool remains unavailable for >5 minutes

---

## Usage Examples

### Query recent trades for MES

```python
from database import repository

orders = await repository.get_recent_orders(symbol="MES", limit=50)
for order in orders:
    print(f"{order['created_at']} {order['symbol']} {order['quantity']} {order['status']}")
```

### Query trading decisions by agent

```python
technical_calls = await repository.get_recent_decisions(
    agent_name="technical",
    symbol="MES",
    limit=100
)

for decision in technical_calls:
    print(f"Signal: {decision['signal']:.2f}, Confidence: {decision['confidence']:.0%}")
    print(f"Reasoning: {decision['reasoning'][:200]}...")
```

### Check portfolio history

```python
snapshots = await repository.get_portfolio_snapshots(limit=48)  # 24 hours of 30-min snapshots

for snap in snapshots:
    print(f"{snap['captured_at']} Equity: ${snap['total_equity']:.2f} Cash: ${snap['cash_balance']:.2f}")
```

### Safety event timeline

```python
safety_events = await repository.get_safety_events(resolved=False, limit=50)

for event in safety_events:
    print(f"[{event['created_at']}] {event['event_type']}: {event['reason']}")
    print(f"  Details: {event['details']}")
```

---

## Performance Considerations

### Query Performance

- **Indexes on:** `symbol`, `created_at`, `status` for orders
- **Indexes on:** `agent_name`, `symbol`, `created_at` for decisions
- **Index on:** `captured_at` for snapshots
- **Typical query latency:** <50ms for recent 100 rows

### Connection Pool

- Min: 2, Max: 10 connections
- Statement caching enabled for prepared statements
- Max cached statement: 15KB
- Connections recycled on timeout

### Storage

- **Estimated growth:** ~1MB per 1000 trading decisions
- **30-day retention (paper trading):** ~30-50MB
- **Live trading (10 decisions/min):** ~10-20MB per month

### Recommendations

For production use:
- Enable WAL (Write-Ahead Logging)
- Set `shared_buffers = 256MB` in postgresql.conf
- Set `effective_cache_size = 1GB`
- Enable autovacuum
- Backup daily via `pg_dump` or streaming replication

---

## Debugging

### Check pool status

```python
from database.connection import get_pool

pool = get_pool()
if pool:
    print(f"Pool active: min={pool._minsize}, max={pool._maxsize}")
else:
    print("Pool not initialized")
```

### Test connection

```bash
psql -U jarvis -d jarvis_trader -c "SELECT COUNT(*) FROM orders;"
```

### Monitor logs

```bash
tail -f logs/jarvis_trader.log | grep "\[DB\]"
```

Look for:
- `[DB] PostgreSQL pool initialized`
- `[DB] Order X inserted`
- `[DB] Portfolio snapshot X`
- `[DB] Safety event X logged`
- `[DB] Query failed` (warnings, not errors if system continues)

---

## Future Enhancements

1. **Reconnection logic** — automatic pool recovery on network flap
2. **Query caching** — Redis integration for recent decision lookups
3. **Analytics materialization** — pre-computed win rate, Sharpe ratio
4. **Time-series export** — export to QuestDB for high-frequency data
5. **API endpoints** — `/trades`, `/decisions`, `/portfolio/history` routes
6. **Real-time streaming** — WebSocket for live decision feed
7. **Archival** — Auto-compress old records to cold storage

---

## Quick Start

```bash
# 1. Start Postgres
brew services start postgresql    # macOS
sudo systemctl start postgresql   # Linux

# 2. Create database and user
createdb -U postgres jarvis_trader
psql -U postgres -d jarvis_trader -f infrastructure/postgres/init.sql

# 3. Update .env
echo "POSTGRES_URL=postgresql://jarvis:jarvis@localhost:5432/jarvis_trader" >> engine/.env

# 4. Install packages
cd engine && pip install -r requirements-core.txt

# 5. Start JARVIS TRADER
uvicorn main:app --reload --port 8010
```

Watch for startup log:
```
✅ PostgreSQL pool initialized for trade logging
```

Then make trades and check the audit trail:

```bash
psql -U jarvis -d jarvis_trader -c "SELECT COUNT(*) FROM orders;"
psql -U jarvis -d jarvis_trader -c "SELECT COUNT(*) FROM agent_decisions;"
```

---

## Support

For issues:
1. Check PostgreSQL is running: `psql -U postgres -c "SELECT version();"`
2. Verify credentials in `.env`
3. Check logs for `[DB]` messages
4. Run `psql -U jarvis -d jarvis_trader` to test connection
5. Look for connection pool warnings in startup phase

