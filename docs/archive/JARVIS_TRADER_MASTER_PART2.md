# JARVIS TRADER -- Master Technical Document (Part 2)

*Sections 1.6 through 1.10 | Version 1.0 | 2026-03-30*
*Companion to JARVIS_TRADER_MASTER.md (Sections 1.1-1.5)*

---

## 1.6 Risk Management & Safety Layer

The safety layer is the most critical subsystem in JARVIS TRADER. It is implemented entirely in hardcoded Python -- no LLM reasoning exists anywhere in the risk path. The design follows the TradeTrap paper principle: portfolio state of record comes from the broker API, never from agent memory. Hard limits cannot be overridden by agent reasoning.

**Source files:**
- `engine/risk/safety_layer.py` -- SafetyLayer class (703 lines)
- `engine/risk/loss_tracker.py` -- ConsecutiveLossTracker class (339 lines)
- `engine/risk/pnl_monitor.py` -- PnLMonitor class (439 lines)
- `engine/health_monitor.py` -- standalone health polling daemon (224 lines)

### 1.6.1 Circuit Breakers (Hardcoded Python, NOT LLM-Controlled)

Every circuit breaker is a deterministic threshold check inside `SafetyLayer.check_order()`. The method runs 9 sequential checks; the first failure returns `RiskCheckResult(approved=False)` and blocks the order from reaching any broker. No LLM has access to modify these thresholds at runtime. They are set via `.env` at engine startup and remain immutable for the session.

**Circuit Breaker 1 -- Kill Switch Gate**
- Threshold: `_kill_switch_active == True`
- Trigger: Any prior activation of the kill switch (manual, automated, or emergency)
- Action: Immediately returns `approved=False` with reason "Kill switch active: {reason}"
- Reset: Manual deactivation only via `POST /safety/kill-switch/deactivate` (Tier 3)
- Code location: `safety_layer.py` line 198

**Circuit Breaker 2 -- Live Trading Gate**
- Threshold: `LIVE_TRADING_ENABLED == False` in settings
- Trigger: Environment variable not set to True
- Action: Returns `approved=False` with reason "Live trading is disabled"
- Reset: Change `LIVE_TRADING_ENABLED=True` in `.env` and restart engine
- Purpose: Prevents any broker submission during paper-only mode
- Code location: `safety_layer.py` line 205

**Circuit Breaker 3 -- Human Approval Gate**
- Threshold: `REQUIRE_HUMAN_APPROVAL == True` in settings
- Trigger: Default configuration requires human confirmation
- Action: Returns `approved=False` with reason "Human approval required"
- Reset: Change `REQUIRE_HUMAN_APPROVAL=False` in `.env` (Tier 3 decision)
- Code location: `safety_layer.py` line 212

**Circuit Breaker 4 -- Daily Loss Limit**
- Threshold: `-2%` of portfolio equity (`MAX_DAILY_LOSS_PCT=0.02`)
- Data source: PnLMonitor (IB Gateway -> SQLite -> in-memory fallback) when available; otherwise `_daily_realized_pnl` in-memory value
- Trigger: `daily_pnl < -(portfolio_equity * 0.02)`
- Action: Activates kill switch with reason `DAILY_LOSS_LIMIT`, returns `approved=False`
- Reset: Manual kill switch deactivation only
- WhatsApp alert: Sent automatically on activation via `get_notifier().alert_kill_switch()`
- Code location: `safety_layer.py` lines 218-232

**Circuit Breaker 5 -- Maximum Drawdown**
- Threshold: `-10%` from peak equity (`MAX_DRAWDOWN_PCT=0.10`)
- Data source: PnLMonitor drawdown calculation (reads from SQLite peak history), or in-memory equity peak comparison
- Trigger: `drawdown > 0.10` (i.e., current equity is 10%+ below peak)
- Action: Activates kill switch with reason `MAX_DRAWDOWN`, returns `approved=False`
- Early warning: At 80% of limit (8% drawdown), a warning is appended but order proceeds
- Reset: Manual kill switch deactivation + investigation required
- Code location: `safety_layer.py` lines 237-266

**Circuit Breaker 6 -- Single Order Value**
- Threshold: `$5,000` per order (`MAX_SINGLE_ORDER_VALUE=5000.0`)
- Trigger: `order.estimated_value > 5000.0`
- Action: Returns `approved=False` with reason showing value vs limit
- Reset: N/A -- submit a smaller order
- Code location: `safety_layer.py` lines 268-273

**Circuit Breaker 7 -- Position Size Limit**
- Threshold: `5%` of portfolio equity (`MAX_POSITION_SIZE_PCT=0.05`)
- Trigger: `(order.estimated_value / portfolio_equity) > 0.05`
- Action: Returns `approved=False` with position pct vs limit
- Reset: N/A -- submit a smaller position
- Code location: `safety_layer.py` lines 275-281

**Circuit Breaker 8 -- Order Rate Throttle (Anti-Runaway)**
- Threshold: `10 orders per minute` (`MAX_ORDERS_PER_MINUTE=10`)
- Implementation: Sliding window of timestamps, pruned to last 60 seconds
- Trigger: `len(recent_timestamps) >= 10` within 60-second window
- Action: Activates kill switch with reason `ANOMALOUS_ORDER_RATE`, returns `approved=False`
- Purpose: Prevents runaway loops from malfunctioning LLM agents
- Reset: Manual kill switch deactivation
- Code location: `safety_layer.py` lines 283-295

**Circuit Breaker 9 -- Futures Contract Limit**
- Threshold: `MAX_CONTRACTS_PER_INSTRUMENT` (configurable, default 2)
- Trigger: `abs(order.quantity) > MAX_CONTRACTS_PER_INSTRUMENT`
- Action: Returns `approved=False` showing requested vs max contracts
- Reset: N/A -- submit fewer contracts
- Code location: `safety_layer.py` lines 297-302

**Circuit Breaker 10 -- Consecutive Loss Halt**
- Threshold: 7 consecutive losses globally (`CONSECUTIVE_LOSS_HALT=7`)
- Trigger: Loss tracker reports `is_halted() == True`
- Action: Returns `approved=False` with halt reason and resume time
- Reset: Wait 24 hours (auto-expiry) OR manual reset via `/safety/loss-tracker/reset`
- Code location: `safety_layer.py` lines 304-311

**Margin Utilization Check**
- Threshold: `40%` of available margin (`MAX_MARGIN_UTILIZATION=0.40`)
- Configured in `.env` as `MAX_MARGIN_UTILIZATION=0.40`
- When IB Gateway is connected, margin data is read from the broker account summary
- If margin utilization exceeds 40%, new orders are blocked

### 1.6.2 Kill Switch Architecture

The kill switch is a binary halt mechanism with three logical states:

| State | Value | Description |
|-------|-------|-------------|
| ARMED | `_kill_switch_active = False` | Normal monitoring -- all circuit breakers active, trading permitted |
| TRIGGERED | `_kill_switch_active = True` | Trading halted -- all orders rejected, reason logged |
| MANUAL_OVERRIDE | N/A (deactivation path) | Emergency bypass -- only via human action, logged with timestamp and reason |

**Kill Switch Reasons (KillSwitchReason enum):**

| Reason | Enum Value | Trigger |
|--------|------------|---------|
| `MANUAL` | `"manual"` | Human activates via API or dashboard |
| `DAILY_LOSS_LIMIT` | `"daily_loss_limit"` | Daily P&L exceeds -2% of equity |
| `MAX_DRAWDOWN` | `"max_drawdown"` | Drawdown exceeds -10% from peak |
| `MARKET_CIRCUIT_BREAKER` | `"market_circuit_breaker"` | Market-wide halt (NYSE/CME) |
| `DATA_FEED_LOSS` | `"data_feed_loss"` | Stale or missing market data |
| `BROKER_DISCONNECT` | `"broker_disconnect"` | IB Gateway connection lost |
| `ANOMALOUS_ORDER_RATE` | `"anomalous_order_rate"` | >10 orders in 60 seconds |

**Activation Flow:**
1. Trigger condition detected (automated) or manual API call
2. `_kill_switch_active` set to `True`
3. `_kill_switch_reason` set to the specific `KillSwitchReason` enum
4. CRITICAL log entry: "KILL SWITCH ACTIVATED: {reason}"
5. Async task: log event to PostgreSQL via `_log_safety_event()`
6. Async task: WhatsApp alert via `get_notifier().alert_kill_switch(reason)`
7. Async task: WebSocket event via `emit_kill_switch_change(active=True, reason=reason)`
8. All subsequent `check_order()` calls return `approved=False` immediately

**Deactivation Flow (Tier 3 -- Human Approval Required):**
1. Matt calls `POST /safety/kill-switch/deactivate` (dashboard button or curl)
2. `deactivate_kill_switch(authorized_by="matt_dashboard")` called
3. `_kill_switch_active` set to `False`, `_kill_switch_reason` cleared
4. INFO log: "Kill switch deactivated by: matt_dashboard"
5. Async task: log deactivation event to PostgreSQL
6. Async task: WebSocket event broadcast
7. Trading resumes on next `check_order()` call

**Critical constraint: No LLM agent has authority to deactivate the kill switch.** The deactivation endpoint is a direct API call that must be initiated by a human. The `authorized_by` parameter is logged for audit trail.

**API Endpoints:**
```
POST /safety/kill-switch/activate?reason=manual_test
POST /safety/kill-switch/deactivate
GET  /safety/status
GET  /safety/circuit-breakers
GET  /safety/config
POST /safety/reset-daily-pnl
GET  /safety/loss-tracker
```

### 1.6.3 Consecutive Loss Tracker

The `ConsecutiveLossTracker` is a persistence-backed module that tracks losing streaks and automatically reduces position sizing as losses accumulate. State is persisted to `engine/data/loss_tracker.json` and survives application restarts.

**Position Size Modulation Rules:**

| Consecutive Losses | Multiplier | Effect | Example (base qty=2) |
|--------------------|------------|--------|----------------------|
| 0-2 | 1.0x | Normal sizing | 2 contracts |
| 3-4 | 0.5x | Half size | 1 contract |
| 5-6 | 0.25x | Quarter size | 1 contract (min 1) |
| 7+ | 0.0x (HALT) | Trading paused 24 hours | 0 contracts -- order rejected |

**Configuration (from `.env`):**
```
CONSECUTIVE_LOSS_HALF_SIZE=3
CONSECUTIVE_LOSS_QUARTER_SIZE=5
CONSECUTIVE_LOSS_HALT=7
CONSECUTIVE_LOSS_HALT_HOURS=24
```

**Tracking Behavior:**
- **Global counter**: Increments on every losing trade across all symbols
- **Per-symbol counter**: Tracks losses per instrument independently
- **Winner resets everything**: A single profitable trade resets both global and per-symbol counters to 0
- **Halt auto-expiry**: After 24 hours, the halt clears automatically; `is_halted()` returns False and the halt_until timestamp is cleared
- **Manual reset**: `POST /safety/loss-tracker/reset` or `safety_layer.reset_loss_tracker()`

**Persistence Format (`loss_tracker.json`):**
```json
{
  "global_consecutive_losses": 3,
  "symbol_losses": {
    "MCL": 2,
    "MNQ": 1
  },
  "last_trade_symbol": "MNQ",
  "last_trade_timestamp": "2026-03-30T14:22:00+00:00",
  "halt_until": null
}
```

**Integration with SafetyLayer:**
- `check_order()` calls `_loss_tracker.is_halted()` first -- if halted, order is rejected
- If not halted, `_loss_tracker.get_position_size_multiplier()` is called
- If multiplier < 1.0, a new `OrderRequest` is created with reduced quantity
- The reduced quantity is clamped to a minimum of 1 (never zero unless halted)
- A warning is appended: "Consecutive losses: {N} -- position size reduced by {pct}"

### 1.6.4 P&L Monitor (PnLMonitor)

The PnLMonitor is the ground-truth P&L data source for the safety layer. It implements a three-tier data priority cascade:

| Priority | Source | Availability | Accuracy |
|----------|--------|-------------|----------|
| 1 (highest) | IB Gateway | When IBKR connected | Real-time broker data |
| 2 | SQLite | Always (after first EOD snapshot) | End-of-day persisted |
| 3 (fallback) | In-memory PortfolioTracker | Always | Session-only paper data |

**Key methods consumed by SafetyLayer:**
- `get_daily_pnl()` -> `float`: Today's realized + unrealized P&L in dollars
- `get_drawdown_pct()` -> `float`: Current drawdown from peak as negative fraction
- `get_peak_balance()` -> `float`: Highest account balance from SQLite history
- `should_halt_trading(daily_loss_limit_pct, drawdown_limit_pct)` -> `(bool, str)`
- `record_eod_snapshot()` -> `bool`: Writes today's P&L to SQLite at market close

**EOD Snapshot Scheduling:**
- Triggered by `EODScheduler` at 4:00 PM ET daily
- Writes to SQLite `daily_pnl` table: date, starting_balance, ending_balance, realized_pnl, unrealized_pnl, total_trades, winning_trades, losing_trades, max_drawdown
- Also triggers WhatsApp EOD summary via the EODScheduler

### 1.6.5 Emergency Protocols (EP-1 through EP-6)

**EP-1: Engine Crash**
- Detection: `health_monitor.py` polls `GET /health` every 60 seconds
- Timeout: 10 seconds per request (`REQUEST_TIMEOUT=10`)
- Alert: If engine unreachable, WhatsApp alert sent within 60 seconds
- Alert cooldown: 5 minutes between repeated DOWN alerts (`ALERT_COOLDOWN=300`)
- Recovery alert: When engine comes back online, sends "JARVIS Engine RECOVERED" via WhatsApp
- Manual restart: `cd engine && .venv\Scripts\python -m uvicorn main:app --port 8010`
- Auto-restart: Not currently implemented -- requires PM2 or systemd (documented in `PAPER_TRADING_RUNBOOK.md`)

**EP-2: IB Gateway Disconnect**
- Detection: `KillSwitchReason.BROKER_DISCONNECT`
- Action: Cancel all pending orders via IB API, log all open positions
- Alert: WhatsApp notification with disconnect timestamp
- Recovery: IB Gateway auto-reconnects; PnLMonitor falls through to SQLite/memory
- Manual intervention: Restart IB Gateway, verify port 7497 reachable

**EP-3: Data Feed Failure**
- Detection: `KillSwitchReason.DATA_FEED_LOSS`
- Action: Halt signal generation -- do NOT trade on stale data
- Threshold: Quote age > 2 seconds triggers data feed loss
- Recovery: Verify Yahoo Finance / Polygon / Finnhub API keys and connectivity
- Kill switch activates: Requires human deactivation after data confirmed fresh

**EP-4: Database Corruption**
- Detection: `db_manager.health_check()` fails during `/health` endpoint
- Action: Log error, continue with in-memory fallback for P&L tracking
- Alert: Health endpoint returns `database: "error"` status
- Recovery: Stop engine, inspect `data/jarvis_trader.db`, restore from backup if needed
- PnLMonitor gracefully degrades: falls through to in-memory PortfolioTracker

**EP-5: Runaway Loss (>-5% in Single Day)**
- Detection: Daily loss exceeds 2x the normal circuit breaker threshold
- Action: Kill switch activates at -2% (EP-5 threshold is the "extreme" case beyond normal -2%)
- Escalation: At -5%, the situation requires a phone call to resume -- this is a standing human rule (not enforced in code, enforced by Matt's personal rules)
- The safety layer has no -5% specific trigger; the -2% kill switch is the automated gate

**EP-6: API Key Compromise**
- Detection: Manual discovery or anomalous API usage
- Action: Immediate engine shutdown, revoke all API keys
- Alert: WhatsApp notification + manual investigation
- Recovery: Rotate Anthropic API key, Twilio credentials, Polygon key
- Prevention: Keys stored in `.env` (gitignored), never committed to repository

### 1.6.6 IB Gateway Safety

**Port Configuration (CRITICAL):**

| Port | Purpose | Status |
|------|---------|--------|
| 7497 | IB Gateway Paper Trading | ALLOWED -- the only connection port during paper phase |
| 7496 | IB Gateway Live Trading | BLOCKED until Phase 2 (June 2026+) |
| 4001 | TWS Live API | BLOCKED -- hardcoded exclusion |
| 4002 | TWS Paper API | BLOCKED -- using IB Gateway instead |

**Environment variables controlling port:**
```
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1
IBKR_PAPER_MODE=True
IB_GATEWAY_HOST=127.0.0.1
IB_GATEWAY_PORT=7497
```

**Paper order submission path:**
1. Signal generated by pipeline -> `submit_paper_order()` called on SafetyLayer
2. Kill switch check (early exit if active)
3. Build `OrderRequest` from parameters
4. Run full `check_order()` with all 10 circuit breaker checks
5. If `_ib_gateway is None`: log as dry-run, return `routed_to_ib=False`
6. If IB Gateway not connected: log error, return `routed_to_ib=False`
7. Call `_ib_gateway.place_paper_order()` on port 7497
8. Return `routed_to_ib=True` with IB order ID

**Futures root detection (heuristic in safety_layer.py):**
```python
_FUTURES_ROOTS = {
    "MES", "MNQ", "M2K", "MCL", "MGC", "MHG", "MSI",
    "ES", "NQ", "RTY", "CL", "GC", "HG",
}
```

### 1.6.7 Safety Event Logging

All safety events are logged to PostgreSQL asynchronously via `_log_safety_event()`. The method is wrapped in try/except and never blocks execution -- if the database is unavailable, the event is logged to the application log only.

Events logged:
- Kill switch activation (with reason and message)
- Kill switch deactivation (with authorized_by)

WhatsApp alerts are sent for:
- Kill switch activation (any reason)
- Daily loss exceeding -1.5% (early warning -- configured in pipeline)
- 3+ consecutive losses (via loss tracker)
- Engine DOWN (via health_monitor.py)
- Engine RECOVERED (via health_monitor.py)
- Trade signals (LONG/SHORT -- via scheduler with 2-hour cooldown)
- MGC daily ENTRY_NOW signals (via scheduled job)
- EOD summary (via EODScheduler)

---

## 1.7 VIX Regime Reference (CANONICAL 6-Tier)

This is the ONE authoritative VIX tier system for JARVIS TRADER. All other documents, dashboards, and configuration files must reference this table. Any conflict between this section and another document is resolved in favor of this table.

### 1.7.1 Canonical VIX Tiers

| Tier | VIX Range | Label | Position Sizing Multiplier | Trading Posture |
|------|-----------|-------|---------------------------|-----------------|
| 1 | < 12 | VERY_LOW | 1.0x (full size) | Watchful calm -- snap reversals common |
| 2 | 12-16 | LOW | 1.0x (full size) | Favorable conditions for STC strategy |
| 3 | 16-20 | NORMAL | 1.0x (full size) | Baseline conditions -- standard operations |
| 4 | 20-25 | ELEVATED | 0.75x (reduce) | Volatility rising -- tighter stops |
| 5 | 25-30 | HIGH | 0.50x (half size) | Liberation Day territory -- caution |
| 6 | > 30 | EXTREME | 0.25x (minimum) | Severe market stress -- survival mode |

### 1.7.2 Per-Regime Trading Notes

**Tier 1 -- VERY_LOW (VIX < 12):**
- Deceptive calm -- historically precedes sharp reversals
- NOT a free pass for aggressive sizing
- Full position size allowed but watch for VIX expansion signals
- STC signals may be less reliable due to compressed ranges
- Mean-reversion signals more likely to work here

**Tier 2 -- LOW (VIX 12-16):**
- Ideal trading conditions for the STC strategy
- Normal stop/target multiples apply (per instrument INSTRUMENT_PARAMS)
- Full-size positions approved
- Most walk-forward windows trained in this environment

**Tier 3 -- NORMAL (VIX 16-20):**
- Baseline operating environment
- All standard parameters apply without modification
- No alerts generated at this level
- Matt does not need to monitor VIX actively

**Tier 4 -- ELEVATED (VIX 20-25):**
- Reduce position size to 0.75x
- Tighten stop losses by 0.5 ATR from baseline
- Avoid counter-trend entries (wait for trend confirmation)
- WhatsApp alert when VIX crosses 20 upward
- Consider skipping midday lull signals entirely
- Regime-adaptive STC may shift parameters in this tier

**Tier 5 -- HIGH (VIX 25-30):**
- "Liberation Day" mode -- named after April 2025 Liberation Day market event
- Position size reduced to 0.50x maximum
- Widen stops by 1.5x from baseline (to accommodate larger swings)
- WhatsApp alert on VIX crossing 25
- Only take signals with very high conviction (confidence > 80%)
- No new positions in first/last 30 minutes of RTH
- Consider pausing automated signals and going to manual-only

**Tier 6 -- EXTREME (VIX > 30):**
- Survival mode -- 0.25x sizing or HALT entirely at Matt's discretion
- WhatsApp alert on VIX crossing 30
- Consider activating kill switch manually
- If already in positions, manage exits only -- no new entries
- Historical events in this tier: COVID crash (Mar 2020), Liberation Day aftermath
- STC strategy has NOT been validated in this regime -- treat with extreme caution

### 1.7.3 VIX Alert Thresholds

| VIX Level | Direction | Action |
|-----------|-----------|--------|
| Crosses 20 upward | Rising | WhatsApp alert: "VIX > 20 -- switching to ELEVATED mode" |
| Crosses 25 upward | Rising | WhatsApp alert: "VIX > 25 -- Liberation Day protocol active" |
| Crosses 30 upward | Rising | WhatsApp alert: "VIX > 30 -- consider HALT" |
| Drops below 20 | Falling | WhatsApp alert: "VIX < 20 -- returning to NORMAL mode" |
| Drops below 25 | Falling | WhatsApp alert: "VIX < 25 -- downgrading from HIGH to ELEVATED" |

### 1.7.4 VIX Data Source

- **Ticker**: `^VIX` via Yahoo Finance (yfinance library)
- **Endpoint**: `GET /macro/snapshot` returns current VIX level in `vix` field
- **Check frequency**: At market open (9:30 AM ET) and every 30 minutes during RTH
- **Fallback**: If Yahoo Finance fails, Finnhub API as secondary source
- **The `/macro/snapshot` response includes**: VIX level, 10Y yield, 2Y yield, DXY, yield curve slope, and macro regime classification

---

## 1.8 Three-Tier Autonomy Model

JARVIS TRADER operates under a strict three-tier autonomy model that governs what the system can do without human involvement. This model exists to prevent runaway losses from LLM errors while allowing JARVIS to be maximally helpful on research and monitoring.

The principle: **conservative autonomy -- research freely, confirm before acting.**

### 1.8.1 Tier 1 -- Fully Autonomous (No Human Approval Needed)

These actions execute continuously without any human intervention. They are read-only or produce only informational output.

| Action | Frequency | Implementation |
|--------|-----------|---------------|
| Engine health checks | Every 60 seconds | `health_monitor.py` polls `GET /health` |
| Market data fetches | Continuous during RTH | `MarketDataManager.initialize()` + scheduled jobs |
| Signal generation and logging | Every 30 minutes | `run_watchlist_analysis()` via APScheduler |
| Paper trade signal evaluation | Per signal | `TradingPipeline.analyze_and_decide()` |
| Performance metric calculations | On demand | `PortfolioTracker.get_performance()` |
| WhatsApp status updates (informational) | Per trigger | `get_notifier().send()` |
| Log rotation and cleanup | Automatic | `RotatingFileHandler` -- 10MB files, 5 backups |
| Walk-forward WFE recalculation | Every 4 weeks | Scheduled or manual trigger |
| Circuit breaker monitoring | Every `check_order()` call | SafetyLayer pre-trade checks |
| VIX level monitoring | Every 30 minutes | `GET /macro/snapshot` in scheduler |
| EOD P&L snapshot | 4:00 PM ET daily | `EODScheduler.record_eod_snapshot()` |
| Decision logging to SQLite | Per pipeline run | `_decision_log.append()` in scheduler |
| Kill switch auto-activation | On threshold breach | SafetyLayer circuit breakers |
| Consecutive loss tracking | Per trade close | `ConsecutiveLossTracker.record_trade()` |

### 1.8.2 Tier 2 -- Recommend-Then-Execute (JARVIS Acts After Confirmation Window)

These actions involve decisions that affect positions or system state. JARVIS generates a recommendation and acts after a brief confirmation window or sends an alert requiring no immediate response.

| Action | Confirmation Window | Mechanism |
|--------|-------------------|-----------|
| New paper trade signals (LONG/SHORT) | 5-minute window to cancel | WhatsApp alert with signal details; if no cancel, proceeds |
| Regime change detections | Alerts, then adjusts sizing | VIX tier change triggers alert + auto-adjust multiplier |
| Kill switch ARM/DISARM recommendations | Alert only -- human decides | WhatsApp recommendation, no auto-action |
| Stop loss adjustments | Pre-approved ATR range only | Adjustments within INSTRUMENT_PARAMS bounds are automatic |
| WhatsApp alerts requiring no action | Immediate | Informational -- VIX changes, EOD summaries, signal logs |
| Position size reduction (consecutive losses) | Immediate | Automatic per loss tracker rules (0.5x, 0.25x) |

### 1.8.3 Tier 3 -- Human Approval Required (NEVER Autonomous)

These actions have material consequences and require explicit human authorization. No LLM, no automated system, and no agent can perform these without Matt's direct involvement.

| Action | Why Human Required | Authorization Method |
|--------|-------------------|---------------------|
| Kill switch deactivation | Resuming trading after emergency halt | `POST /safety/kill-switch/deactivate` via dashboard or curl |
| Live trading activation | Transitioning from paper to real money | Set `LIVE_TRADING_ENABLED=True` + `SCHWAB_READY=True` in `.env` |
| Capital allocation changes | Any modification to base capital amount | Edit `paper_config.py` manually |
| New instrument approval | Adding symbols beyond MCL/MNQ | Walk-forward validation + manual config change |
| API key rotation | Security-sensitive credential changes | Manual `.env` update + engine restart |
| Any action with $ consequence > $500 | Financial impact threshold | Manual review and explicit confirmation |
| Any system config change in paper_config.py | Configuration that affects trading behavior | Manual file edit + engine restart |
| Database schema changes | Structural data changes | Manual migration scripts |
| IB Gateway port change (7497 -> 7496) | Live trading port transition | Manual `.env` update + engine restart |
| Monthly loss tracker reset | Clearing accumulated loss state | `POST /safety/loss-tracker/reset` (manual trigger) |

### 1.8.4 Why This Model

1. **Prevents runaway losses from LLM errors**: Even if an agent hallucinates a "strong buy" signal, the safety layer still gates every order through hardcoded circuit breakers
2. **Preserves human authority over capital at risk**: Matt retains final say on anything that puts real money at risk
3. **Allows JARVIS to be maximally helpful**: Research, monitoring, signal generation, and alerting all run autonomously -- Matt gets the benefit without the risk
4. **Conservative by design**: The system errs on the side of NOT trading rather than trading incorrectly
5. **Audit trail**: Every Tier 2 and Tier 3 action is logged with timestamp, actor, and reason

---

## 1.9 Standing Orders & Proactive Triggers

### 1.9.1 Standing Orders (SO-1 through SO-6)

Standing orders are persistent directives that JARVIS follows every trading day without being asked.

**SO-1: Health Monitoring (Continuous)**
- Frequency: Every 60 seconds, 24/7
- Implementation: `health_monitor.py` daemon
- Polls: `GET http://localhost:8010/health`
- Timeout: 10 seconds per request
- Alert: WhatsApp if engine unreachable for >60 seconds
- Alert cooldown: 5 minutes between repeated DOWN alerts
- Recovery notification: Sends "JARVIS Engine RECOVERED" when engine comes back

**SO-2: Market Scan During RTH (Every 30 Minutes)**
- Frequency: Every 30 minutes, Mon-Fri, 9:00 AM - 3:30 PM CT
- Implementation: APScheduler with CronTrigger `day_of_week="mon-fri", hour="9-15", minute="0,30"`
- Scope: Top 2 futures watchlist symbols + top 3 equities watchlist symbols
- Pipeline: Full 5-stage analysis (Technical -> News -> Social -> Fundamental -> Bull/Bear Debate -> Trade Decision -> Risk Review -> Fund Manager)
- Kill switch check: Skips scan if kill switch is active
- Output: Decision logged to `_decision_log`, WhatsApp alert for non-HOLD signals
- WhatsApp cooldown: 2 hours per symbol to prevent alert flooding

**SO-3: EOD Summary (4:05 PM CT Daily)**
- Frequency: Once daily at 4:05 PM CT on trading days
- Implementation: `EODScheduler` registered on the APScheduler instance
- Content: P&L recap, trade count, win rate, regime status, next-day outlook
- Delivery: WhatsApp message via Twilio
- Also: Writes P&L snapshot to SQLite `daily_pnl` table

**SO-4: Rolling WFE Recalculation (Every 4 Weeks)**
- Frequency: Every 4 weeks (manual trigger or scheduled)
- Scope: MCL 1h (static) and MNQ 1h (adaptive)
- Alert: If WFE drops below 0.40 for either instrument, WhatsApp alert
- Action on WFE drop: If below 0.40, consider pausing paper trading for that instrument
- Re-optimization: If WFE below 0.30, trigger full parameter re-optimization

**SO-5: MGC Daily Signal Scanner (6:00 PM ET / 5:00 PM CT)**
- Frequency: Mon-Fri at 23:00 UTC (6:00 PM ET / 5:00 PM CT)
- Implementation: APScheduler CronTrigger, `run_daily_mgc_signal()` function
- Process: Fetches 90 days of GC=F daily bars, runs `generate_signals()` with adaptive regime
- Output: If ENTRY_NOW signal detected, writes to `engine/backtest/results/pending_signals.json`
- Alert: WhatsApp with direction, entry estimate, stop, target, and regime
- NOTE: MGC paper trading is HALTED (WFE=0.14) -- this scanner runs for research/monitoring only

**SO-6: Kill Switch Monitoring (Continuous)**
- Frequency: Checked on every `check_order()` call (effectively per-trade)
- Scope: Daily P&L, consecutive losses, monthly P&L
- Thresholds: -2% daily loss, 7 consecutive losses, -3% monthly loss
- Auto-activation: Daily loss and consecutive loss triggers are automated
- Monthly loss: Checked manually (not yet automated in code)

### 1.9.2 Proactive Triggers (T-1 through T-24)

Proactive triggers are event-based or time-based actions that fire when specific conditions are met.

#### Time-Based Triggers

**T-1: Futures Pre-Market Check (6:00 AM CT)**
- Action: Check Globex overnight prices for MCL, MNQ, MES
- Data source: `GET /prices/snapshot`
- Purpose: Identify overnight gaps that may affect today's trading
- Delivery: Included in pre-market briefing

**T-2: Pre-Market Briefing (6:30 AM CT)**
- Action: Compile and deliver pre-market intelligence brief
- Content: Overnight futures prices, VIX level, economic calendar, yesterday's performance
- 7-step data collection: Health check, VIX/macro, portfolio review, previous decisions, prices, sentiment, economic calendar
- Delivery: WhatsApp message (automated)
- Matt reviews during his 7-8 AM CT morning window

**T-3: Economic Data Alert (8:30 AM CT)**
- Action: Check for major economic releases (CPI, NFP, FOMC)
- Data source: Economic calendar scan
- If major release: Enable news blackout window (T-20, T-21, T-22)
- If no release: Proceed with normal operations

**T-4: RTH Open -- Activate Signal Scanning (9:30 AM CT / 8:30 AM CT)**
- Action: Scheduler begins 30-minute scan cycle (SO-2)
- First scan fires at 9:00 AM CT (30 min before RTH open)
- Kill switch checked before each scan

**T-5: First 1h Candle Closes -- Initial IB Level Set (9:35 AM CT)**
- Action: First hourly candle closes; STC calculates initial levels
- Purpose: Establishes initial bias, entry zones, IB range
- Signal: May generate first ENTRY_NOW of the day

**T-6: Midday Check (11:30 AM CT)**
- Action: Review open positions, check P&L against daily targets
- Matt's preferred trading window closes at 11:30 AM CT
- Signal quality typically degrades during 11:30 AM - 1:00 PM CT

**T-7: Afternoon Session Opens (1:00 PM CT)**
- Action: Second signal window begins
- Quality: Valid signals but generally lower quality than morning
- Matt's secondary trading window: 1:00 PM - 3:30 PM CT

**T-8: RTH Wind-Down (3:30 PM CT)**
- Action: Begin EOD exit checks for all open 1h positions
- No new entries after 3:30 PM CT
- Exit management only

**T-9: Force-Close All Open Positions (3:59 PM CT)**
- Action: Any open 1h signal positions are closed at market
- Rule: NO overnight holds for 1h signals -- mandatory
- Implementation: EOD exit logic in backtester applies to paper trades

**T-10: EOD Summary Report (4:05 PM CT)**
- Action: Generate and send daily performance summary
- Content: Total P&L, trade count, win rate, max drawdown, regime status
- Delivery: WhatsApp via Twilio
- Database: P&L snapshot written to SQLite

#### Event-Based Triggers

**T-11: VIX Crosses 20 Upward**
- Action: WhatsApp alert, switch to ELEVATED mode (0.75x sizing)
- Priority: Immediate
- Adjustment: Tighter stops, avoid counter-trend entries

**T-12: VIX Crosses 25 Upward**
- Action: WhatsApp alert, Liberation Day protocol (0.50x sizing)
- Priority: Immediate
- Adjustment: Widen stops 1.5x, high-conviction signals only

**T-13: Daily Loss Hits -1.5%**
- Action: Early warning WhatsApp alert
- Priority: High
- Note: This is a warning, not a circuit breaker -- the -2% hard limit triggers kill switch

**T-14: Daily Loss Hits -2%**
- Action: Kill switch auto-activates (circuit breaker 4)
- Priority: CRITICAL
- Recovery: Manual deactivation only (Tier 3)

**T-15: 3 Consecutive Losses**
- Action: Position size reduced to 0.5x automatically
- Alert: WhatsApp notification
- Recovery: Resets on next winning trade

**T-16: Kill Switch Triggers**
- Action: Immediate WhatsApp alert + all trading halted
- Priority: CRITICAL
- Information: Includes reason, timestamp, and current P&L

**T-17: Engine Goes Offline**
- Action: health_monitor.py detects within 60 seconds, WhatsApp alert
- Recovery: Manual restart required
- Alert includes: Failure reason and restart command

**T-18: IB Gateway Disconnects**
- Action: Cancel pending orders, log positions, WhatsApp alert
- Recovery: IB Gateway auto-reconnects or manual restart
- PnLMonitor: Falls through to SQLite/memory sources

**T-19: New Signal Generated (LONG/SHORT)**
- Action: Tier 2 recommendation via WhatsApp
- Content: Symbol, direction, confidence, entry price, stop, target
- Cooldown: 2 hours per symbol (no duplicate alerts)

#### Intelligence Triggers

**T-20: FOMC Meeting Day**
- Action: Auto-enable news blackout for 2-hour window around announcement
- Typical schedule: 1:00 PM CT announcement + press conference
- Blackout window: 12:00 PM - 2:00 PM CT (no new entries)
- Implementation: `engine/backtest/signals.py` news_blackout parameter

**T-21: NFP Friday (Non-Farm Payrolls)**
- Action: Auto-enable news blackout 8:00 AM - 10:00 AM CT
- Frequency: First Friday of each month
- Impact: High-volatility event, avoid entries during initial reaction

**T-22: CPI Release Day**
- Action: Auto-enable news blackout for release window
- Typical schedule: 7:30 AM CT release
- Blackout window: 7:00 AM - 9:00 AM CT

**T-23: Quarter-End (Last Week of Quarter)**
- Action: Reduce sizing to 0.75x (window dressing flows distort price action)
- Affected weeks: Last 5 trading days of March, June, September, December
- Rationale: Institutional rebalancing creates non-fundamental price moves

**T-24: New Month Start**
- Action: Reset monthly loss tracker, send monthly performance summary
- Content: Month P&L, win rate, Sharpe, max drawdown, instrument breakdown
- Delivery: WhatsApp message on first trading day of the month

### 1.9.3 Automated Daily Timeline (Complete Schedule)

All times are Central Time (CT). This schedule applies Monday through Friday on trading days.

```
06:00 CT  Futures pre-market check (T-1)
           - Globex overnight prices: MCL, MNQ, MES
           - Overnight gap detection

06:30 CT  Pre-Market Intelligence Brief delivered (T-2)
           - 7-step data collection runs automatically
           - VIX level, macro regime, economic calendar
           - Yesterday's performance recap
           - Delivered to WhatsApp

07:00 CT  Economic calendar check (T-3)
           - Scan for CPI, NFP, FOMC today
           - If major release: enable news blackout window
           - Matt's morning review window (7:00-8:00 AM CT)

08:00 CT  Matt's active prep window
           - Review WhatsApp briefing
           - Confirm trade plan for the day
           - Check VIX regime tier

08:30 CT  RTH opens (T-4)
           - Scheduler activates signal scanning
           - First scan cycle begins
           - Opening 5-minute avoid period begins (high noise)

09:00 CT  First scheduler scan fires
           - 30-minute cycle begins (SO-2)
           - Pipeline runs on MCL, MNQ

09:35 CT  First 1h candle closes (T-5)
           - Initial STC levels calculated
           - Initial bias determined
           - Matt's primary trading window OPENS

10:05 CT  Second 1h candle signal check
           - Scan fires on schedule

10:35 CT  Third 1h candle signal check
           - Morning session peak activity

11:05 CT  Fourth 1h candle signal check
           - Last scan before midday lull

11:30 CT  Midday lull begins (T-6)
           - P&L check, open position review
           - Signal quality typically degrades
           - Matt's morning window CLOSES
           - Avoid new entries unless strong signal

12:05 CT  Midday scan fires
           - Lower confidence threshold

12:35 CT  Scan fires (midday)

13:00 CT  Afternoon session opens (T-7)
           - Secondary trading window
           - Valid signals but lower quality

13:35 CT  Afternoon signal check

14:05 CT  Fifth 1h candle signal check

14:35 CT  Sixth 1h candle signal check

15:00 CT  Final RTH scan fires

15:30 CT  RTH wind-down begins (T-8)
           - Exit management only
           - No new entries
           - Matt's afternoon window CLOSES

15:59 CT  Force-close all open positions (T-9)
           - Mandatory EOD exit for all 1h signals
           - NO overnight holds

16:05 CT  EOD summary (T-10)
           - P&L recap sent to WhatsApp (SO-3)
           - P&L snapshot written to SQLite
           - Performance metrics calculated

17:00 CT  MGC daily signal scanner (SO-5)
           - Runs at 5:00 PM CT (6:00 PM ET = 23:00 UTC)
           - Research/monitoring only (MGC is HALTED)
```

---

## 1.10 Matt's Trading Context & Personal Rules

### 1.10.1 Trading Windows (All Times Central)

| Window | CT Times | Purpose | Rule |
|--------|----------|---------|------|
| Pre-market | 8:00-8:30 AM | Data check only | NO entries -- review briefing, confirm plan |
| RTH Open avoid | 8:30-9:35 AM | High noise | NO entries -- opening volatility too unpredictable |
| Primary window | 9:35-11:30 AM | PREFERRED | Cleanest price action, highest-quality signals |
| Midday lull | 11:30 AM - 1:00 PM | AVOID | Choppy, low conviction -- skip unless very strong signal |
| Secondary window | 1:00-3:30 PM | Valid but secondary | Lower quality than morning, valid entries acceptable |
| Wind-down | 3:30-3:59 PM | Exit management only | No new entries, manage existing positions for close |
| After-hours | 4:00+ PM | Nothing | All positions closed, review EOD summary when convenient |

### 1.10.2 Absolute Rules (PERMANENT -- NEVER VIOLATE)

These rules are non-negotiable and apply in every market condition, every day, without exception.

1. **Never hold MES/MNQ/MCL/MGC overnight on 1h signals.** EOD exit is mandatory. The 1h strategy is designed for intraday timeframes only. Overnight gaps can blow past stops.

2. **Always respect the -2% daily halt.** No exceptions, no "one more trade," no "I'll get it back." When the circuit breaker trips, trading is done for the day. Period.

3. **Check WhatsApp briefing before any action on signal days.** The pre-market brief (T-2) contains VIX regime, overnight gaps, and economic calendar. No trading without reviewing it first.

4. **Never add to a losing position.** No averaging down on futures. If a trade is losing, the only actions are: hold to stop, exit at market, or tighten stop. Never increase size.

5. **Kill switch authority: Matt alone can deactivate.** No LLM, no agent, no automated system can rearm the kill switch. This is a Tier 3 action requiring human authorization.

6. **Maximum contracts: 2 at any time across ALL instruments combined.** Not 2 per instrument -- 2 total. This limits total portfolio risk exposure.

7. **Paper trading only until June 2026 milestone.** Live trading requires: WFE maintained above thresholds, 30-day forward test passed, 60+ paper trades completed, no EP-3 events in 30 days.

### 1.10.3 Account Phases

**Phase 0 -- Research (COMPLETE)**
- Status: Completed 2026-03-30
- Work done: Walk-forward validation, parameter optimization, 8 backtester bug fixes
- Key results: 2 of 5 instruments cleared (MCL WFE=0.82, MNQ WFE=0.57)
- Duration: ~2 weeks of intensive research
- Deliverables: SUMMARY.md (v2.7), EXECUTIVE_BRIEFING.md (v2.7), BACKTEST_RESEARCH_REPORT.md (1,245 lines)

**Phase 1 -- Paper Trading (CURRENT)**
- Status: Active as of 2026-03-30
- Simulated capital: $25,000 per instrument (MCL and MNQ independent)
- Risk per trade: 0.25% ($62.50 per trade per instrument)
- Instruments: MCL 1h (static params, WFE=0.82) + MNQ 1h (adaptive regime, WFE=0.57)
- Kill switch thresholds: -3% monthly OR 3 consecutive losses on either instrument
- Duration target: 30+ trading days minimum
- Success criteria:
  - Profit Factor > 1.5
  - Sharpe Ratio > 1.0
  - Max Drawdown < 10%
  - Win Rate > 45%
  - Zero unhandled exceptions in 30 days
  - IB Gateway uptime > 99.5%
  - Agent pipeline latency < 30 seconds
- Broker: Interactive Brokers paper account (port 7497)
- Position limit: 1 contract per instrument (MCL, MNQ independent)

**Phase 2 -- Live Phase 1 (Target: June 2026+)**
- Prerequisites (ALL required):
  - 60+ paper trades completed successfully
  - Forward WFE maintained above 0.50 for both instruments
  - No EP-3 (data feed failure) events in last 30 days
  - All success criteria from Phase 1 met
  - Matt reviews and explicitly approves
- Capital: $10,000 real money
- Max position: 1 MES contract (smallest available)
- Risk per trade: 0.25% ($25 per trade)
- Brokerage: Interactive Brokers live account
- Port transition: 7497 (paper) -> 7496 (live) -- requires `.env` change and engine restart
- SCHWAB_READY flag: Must be manually set to True in `.env` (additional safety gate)
- Week 1: 0.25x position size (quarter size)
- Week 2: 0.50x position size (half size)
- Week 3+: 1.00x position size (full)

**Phase 3 -- Scale Up (Target: September 2026+)**
- Prerequisites: Phase 2 shows 3+ consecutive months of profitability
- Add MCL or MNQ at full micro-contract size
- Scale capital based on demonstrated edge
- Gradual increase: one additional instrument or one additional contract per quarter
- Monthly review meetings to evaluate scaling decisions

### 1.10.4 Matt's Instrument Knowledge

- **Primary instruments**: Micro futures only -- MCL (crude oil 1h), MNQ (micro Nasdaq 1h)
- **Familiar with**: ThinkorSwim platform, IBKR TWS/Gateway
- **Uses JARVIS for**: Signal confirmation, automated scanning, performance tracking
- **Does NOT trade**: Forex, cryptocurrency, individual stocks, full-size futures, options (except research)
- **Does NOT hold**: Overnight futures positions (ever, on 1h signals)
- **VIX discipline**: Check VIX before every session, respect regime-based sizing adjustments
- **Preferred style**: Systematic, rules-based -- does not override JARVIS signals with discretion
- **Risk tolerance**: Conservative -- 0.25% per trade, max 2 contracts total, no leverage above micro contracts

### 1.10.5 Work Schedule Context

Matt's primary job is running Greenfield Metal Sales (steel distributor, full-time). Trading is NOT his primary activity -- it is automated and managed by JARVIS TRADER.

**Daily routine:**
- **7:00-8:00 AM CT**: Morning review (before work). Check overnight futures, review WhatsApp pre-market briefing (T-2). This is the primary time Matt interacts with JARVIS TRADER.
- **8:00 AM - 5:00 PM CT**: At work. Matt does NOT sit at a trading desk during regular trading hours. He relies entirely on JARVIS alerts via WhatsApp.
- **After 5:00 PM CT**: Evening review. Check EOD summary (T-10), review next-day outlook, approve any Tier 3 actions if needed.

**Implication for system design:**
- All alerts must be WhatsApp-first (Matt may not see dashboard during RTH)
- Tier 2 actions use a 5-minute confirmation window (default: proceed if no cancel)
- Tier 3 actions wait indefinitely for Matt's response (no timeout)
- EOD summary is the primary daily touchpoint -- must be comprehensive
- Morning briefing must be delivered early enough for Matt to review before work
- Dashboard is for deeper analysis during evening review, not real-time trading

**Approval channels:**
- WhatsApp response to JARVIS alerts (primary -- fastest)
- Dashboard button click (secondary -- during evening review)
- Direct API call via curl (tertiary -- for technical operations)
- Manual `.env` file edit + engine restart (for Phase/config changes only)

### 1.10.6 Paper Trading Configuration Reference

**MCL 1h -- ACTIVE (WFE=0.82 EXCELLENT)**

| Parameter | Value |
|-----------|-------|
| Capital | $25,000 |
| Risk/trade | 0.25% ($62.50) |
| Config | Static params, regime_filter=ON, adaptive_regime=OFF |
| STC_OS | 15 |
| STC_OB | 83 |
| Stop | 0.90 ATR |
| T1 | 1.50 ATR |
| T2 | 2.618 ATR |
| Kill switch | -3% monthly OR 3 consecutive losses |

**MNQ 1h -- ACTIVE (WFE=0.57 GOOD)**

| Parameter | Value |
|-----------|-------|
| Capital | $25,000 |
| Risk/trade | 0.25% ($62.50) |
| Config | adaptive_regime=ON, volume_filter=OFF, mtf_filter=OFF |
| STC_OS | 15 |
| STC_OB | 92 |
| Stop | 0.70 ATR |
| T1 | 1.00 ATR |
| T2 | 1.80 ATR |
| Kill switch | -3% monthly OR 3 consecutive losses |

**Configuration files:**
- `engine/backtest/paper_config.py` -- paper trading parameters
- `engine/backtest/signals.py::INSTRUMENT_PARAMS` -- 7-element tuples per instrument
- `engine/.env` -- risk parameters, broker config, API keys
- `PAPER_TRADING_APPROVAL.md` -- approval documentation
- `PAPER_TRADING_RUNBOOK.md` -- operational procedures

### 1.10.7 Re-Evaluation Schedule

| Interval | Action | Trigger |
|----------|--------|---------|
| Every 4 weeks | Rolling WFE recalculation (SO-4) | Append new data, re-run walk-forward |
| Monthly | Performance review against Phase 1 criteria | First trading day of month (T-24) |
| Quarterly | Full parameter re-optimization if WFE drops below 0.40 | Manual trigger |
| Annually | Full strategy assessment -- consider new signal layers | Manual trigger |
| On demand | If 3 consecutive losing months | Kill switch + full review |

---

*End of Part 2 (Sections 1.6-1.10)*
*Total sections covered: Risk Management, VIX Regime, Autonomy Model, Standing Orders, Personal Rules*
*Source files referenced: safety_layer.py, loss_tracker.py, pnl_monitor.py, health_monitor.py, main.py, SUMMARY.md, EXECUTIVE_BRIEFING.md, PAPER_TRADING_APPROVAL.md, PAPER_TRADING_RUNBOOK.md, TRADING_DAILY_ROUTINE.md*
