# JARVIS TRADER — Paper Trading Runbook

**Target Launch:** April-May 2026 | **Duration:** 30-day forward test | **Mode:** Interactive Brokers Gateway (Paper Account)

---

## Section 1: Prerequisites

### 1.1 Interactive Brokers Account Setup

JARVIS TRADER requires an **Interactive Brokers (IBKR) paper trading account** for the 30-day forward test. Paper accounts are free and allow live market data with simulated execution.

**Steps:**

1. **Create IBKR Account**
   - Visit [Interactive Brokers Account Opening](https://www.ibkr.com/en/home.php)
   - Register for a paper trading account (no deposit required)
   - Account approval is typically instant
   - Note your Account ID (e.g., `DU123456` or similar)

2. **Enable API Access**
   - Log into IBKR Account Management
   - Navigate to Account Settings → User Settings → API
   - Enable "Socket API"
   - Ensure "Trusted IPs" includes your development machine's IP (or leave blank if on localhost)

### 1.2 IB Gateway Installation

IB Gateway is a lightweight gateway that exposes the IBKR API over TCP sockets. It is REQUIRED for JARVIS TRADER to execute paper trades.

**Hardware/Software Requirements:**

- **Java Runtime Environment (JRE):** Version 11+ required. IB Gateway uses Java internally.
  - Download from: https://www.oracle.com/java/technologies/downloads/
  - Or install via package manager: `brew install openjdk` (macOS) / `apt install default-jre` (Linux)
  - Verify installation: `java -version`

- **IB Gateway Application:** Available for Windows, macOS, and Linux
  - Download from: [IB Gateway Download Page](https://www.interactivebrokers.com/en/trading/platforms/ib-gateway.php)
  - No installation required; extract and run

**Installation Steps:**

1. Download IB Gateway for your OS (Windows/macOS/Linux)
2. Extract to a stable directory (e.g., `C:\Program Files\IBGateway\` or `~/IBGateway/`)
3. Launch IB Gateway application
4. Log in with your IBKR credentials
5. Verify "Socket API" is enabled in the TWS connection settings

### 1.3 IB Gateway API Socket Configuration

IB Gateway exposes the API on configurable TCP ports. JARVIS TRADER expects:

- **Paper Trading:** Port 4002 (IB Gateway default for paper)
- **Live Trading (future):** Port 4001 (PERMANENTLY BLOCKED during paper phase)

**Note:** Port 7497 is the TWS (desktop client) port and is NOT used by JARVIS TRADER. IB Gateway communicates on port 4002 for paper trading only.

**Verify Configuration in IB Gateway:**

1. Open IB Gateway
2. Navigate to: Edit → Configuration → API → Settings
3. Confirm:
   - Socket Port for Paper Trading: `4002` (default)
   - Socket Port for Live Trading: `4001` (disabled during paper test)
   - Enable "Allow connections from any IP" (or restrict to localhost)
4. **Important:** Restart IB Gateway after any configuration changes

### 1.4 Network Connectivity Test

Before starting JARVIS TRADER, verify IB Gateway is reachable:

```bash
# Test connectivity to IB Gateway (assuming it's running on localhost:4002)
nc -zv 127.0.0.1 4002
# Expected output: Connection to 127.0.0.1 port 4002 [tcp/*] succeeded!

# Or use Python:
python -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(('127.0.0.1', 4002))
    s.close()
    print('✓ IB Gateway is reachable on port 4002')
except Exception as e:
    print(f'✗ Connection failed: {e}')
"
```

---

## Section 2: Environment Configuration

### 2.1 Full .env Variable Checklist

Create or update `engine/.env` with ALL the following variables. Use `engine/.env.example` as a template.

```bash
# ──────────────────────────────────────────────────────────────────────────
# PAPER TRADING MODE (CRITICAL)
# ──────────────────────────────────────────────────────────────────────────
PAPER_TRADING=True
PAPER_TRADING_BROKER=IB_GATEWAY

# ──────────────────────────────────────────────────────────────────────────
# INTERACTIVE BROKERS GATEWAY (Paper Trading)
# ──────────────────────────────────────────────────────────────────────────
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=1
IBKR_PAPER_MODE=True
IB_GATEWAY_HOST=127.0.0.1
IB_GATEWAY_PORT=4002
IB_ACCOUNT_ID=YOUR_IBKR_ACCOUNT_ID  # e.g., DU123456

# ──────────────────────────────────────────────────────────────────────────
# AUTONOMY & SAFETY
# ──────────────────────────────────────────────────────────────────────────
LIVE_TRADING_ENABLED=False
REQUIRE_HUMAN_APPROVAL=True

# ──────────────────────────────────────────────────────────────────────────
# RISK PARAMETERS
# ──────────────────────────────────────────────────────────────────────────
MAX_POSITION_SIZE_PCT=0.05
MAX_DAILY_LOSS_PCT=0.02
MAX_DRAWDOWN_PCT=0.10
MAX_ORDERS_PER_MINUTE=10
MAX_CORRELATED_EXPOSURE_PCT=0.20
PRICE_COLLAR_PCT=0.05
MAX_SINGLE_ORDER_VALUE=5000.0
MAX_MARGIN_UTILIZATION=0.40
CONSECUTIVE_LOSS_HALF_SIZE=3
CONSECUTIVE_LOSS_QUARTER_SIZE=5
CONSECUTIVE_LOSS_HALT=7
CONSECUTIVE_LOSS_HALT_HOURS=24

# ──────────────────────────────────────────────────────────────────────────
# INSTRUMENTS TO TRADE
# ──────────────────────────────────────────────────────────────────────────
# APPROVED (active paper, Tier-3 2026-05-24): MES (1h, p_edge 0.75), MGC (1h, p_edge 0.6842)
# HALTED (DO_NOT_TRADE): MCL (WFE 0.82), MNQ (WFE 0.57) — strategy hypotheses exhausted / fail gate v2
# REJECTED: M2K (SMA/ORB/Donchian all FAIL 2026-05-24)
# Watchlist drives pipeline signals/dashboard visibility; only MES/MGC generate paper orders.
FUTURES_WATCHLIST=MES,MNQ,MCL,MGC
OPTIONS_WATCHLIST=SPY,QQQ,AAPL,TSLA

# ──────────────────────────────────────────────────────────────────────────
# MARKET DATA APIs (Polygon.io, Finnhub, Alpaca)
# ──────────────────────────────────────────────────────────────────────────
POLYGON_API_KEY=pk_live_YOUR_KEY_HERE
FINNHUB_API_KEY=YOUR_KEY_HERE
ALPACA_API_KEY=YOUR_KEY_HERE
ALPACA_SECRET_KEY=YOUR_SECRET_HERE
ALPACA_PAPER=True

# ──────────────────────────────────────────────────────────────────────────
# ANTHROPIC LLM (for agents)
# ──────────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE
LLM_PROVIDER=anthropic
ANALYST_MODEL=claude-sonnet-4-6
TRADER_MODEL=claude-opus-4-6
FAST_MODEL=claude-haiku-4-5-20251001

# ──────────────────────────────────────────────────────────────────────────
# DATABASES (Docker Compose)
# ──────────────────────────────────────────────────────────────────────────
POSTGRES_URL=postgresql://jarvis:jarvis@localhost:5432/jarvis_trader
REDIS_URL=redis://localhost:6379
QUESTDB_HOST=localhost
QUESTDB_PORT=9000

# ──────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS (WhatsApp via Twilio) — OPTIONAL
# ──────────────────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID=AC_YOUR_SID_HERE
TWILIO_AUTH_TOKEN=YOUR_TOKEN_HERE
TWILIO_WHATSAPP_FROM=whatsapp:+1234567890
WHATSAPP_TO=whatsapp:+1234567890

# ──────────────────────────────────────────────────────────────────────────
# SECURITY & LOGGING
# ──────────────────────────────────────────────────────────────────────────
API_KEY=jarvis-dev-key-change-me
LOG_LEVEL=INFO
```

### 2.2 Validation Checklist

Before starting JARVIS TRADER, verify:

```bash
# Check that .env file exists
test -f engine/.env && echo "✓ .env exists" || echo "✗ .env missing"

# Check required variables
python -c "
from pathlib import Path
import os
os.chdir('engine')
from config import settings
print('✓ Config loaded successfully')
print(f'  PAPER_TRADING: {settings.PAPER_TRADING}')
print(f'  IBKR_HOST: {settings.IBKR_HOST}:{settings.IBKR_PORT}')
print(f'  IB_ACCOUNT_ID: {os.getenv(\"IB_ACCOUNT_ID\", \"NOT SET\")}')
"
```

---

## Section 3: Startup Procedure

### 3.1 Pre-Startup Checklist

Before running `start_jarvis.bat`, verify:

- [ ] Java is installed and accessible: `java -version`
- [ ] IB Gateway is installed and extracted
- [ ] IB Gateway is running and logged in (should show "Connected" status)
- [ ] Network connectivity test passes (Section 1.4)
- [ ] `.env` file is configured with all required variables (Section 2)
- [ ] Docker Compose stack is running: `docker-compose ps`

### 3.2 Step-by-Step Startup

**On Windows:**

```batch
# 1. Start IB Gateway (if not already running)
#    Open: C:\Program Files\IBGateway\ibgateway.exe
#    Log in with your IBKR credentials
#    Wait for "Connected" status

# 2. Launch JARVIS TRADER
cd path\to\jarvis-trader
start_jarvis.bat

# 3. The script will automatically:
#    - Initialize the SQLite database
#    - Start Engine on port 8010
#    - Wait for health check
#    - Start Dashboard on port 3010
#    - Launch Health Monitor
#    - Open dashboard in browser
```

**On macOS/Linux:**

```bash
# 1. Start IB Gateway (ensure it's running)
~/IBGateway/ibgateway &

# 2. Start Docker Compose stack (if not already running)
docker-compose up -d

# 3. Initialize database
cd engine
python init_db.py
cd ..

# 4. Start Engine
cd engine
python -m uvicorn main:app --port 8010 &
cd ..

# 5. Start Health Monitor
cd engine
python health_monitor.py &
cd ..

# 6. Start Dashboard
cd dashboard
npm run dev &
cd ..

# 7. Open dashboard
open http://localhost:3010
```

### 3.3 Health Check Verification

After startup, verify all systems are running:

```bash
# Check Engine health
curl http://localhost:8010/health
# Expected response: { "status": "ok", "timestamp": "..." }

# Check IB Gateway connection (via Engine)
curl http://localhost:8010/v1/broker/status
# Expected response: { "connected": true, "broker": "ib_gateway", ... }

# Check database connectivity
curl http://localhost:8010/v1/system/db-status
# Expected response: { "postgres": "connected", "redis": "connected", ... }

# Check that Paper Trading mode is enabled
curl http://localhost:8010/v1/system/config
# Look for: "PAPER_TRADING": true
```

### 3.4 Dashboard Verification

Open the dashboard at `http://localhost:3010` and verify:

- [ ] "Paper Trading Mode" badge visible at top
- [ ] Kill Switch showing "ARMED" (red)
- [ ] IB Gateway connection status: "Connected"
- [ ] Portfolio P&L shows $0 (or current paper balance)
- [ ] Agent pipeline: "Ready" (green)
- [ ] No error messages in logs panel

---

## Section 4: Daily Monitoring Checklist

### 4.1 Morning Routine (Before Market Open)

**Time:** 30 minutes before market open (e.g., 9:00 AM EST for 9:30 AM open)

```bash
# 1. Check overnight errors in logs
tail -n 100 engine/logs/jarvis.log | grep -i "error\|exception\|critical"

# 2. Verify IB Gateway is still connected (port 4002)
curl http://localhost:8010/v1/broker/status
# Look for: "connected": true, "last_heartbeat": <recent_timestamp>

# 3. Review Agent Pipeline Health
curl http://localhost:8010/v1/agents/health
# Expected: all agents show "status": "ready"

# 4. Review Previous Day's Agent Decisions (if this is not the first day)
curl "http://localhost:8010/v1/agents/decisions?date=2026-04-01&limit=20"
# Analyze: Were signals generated? Did risk layer reject any trades? Why?

# 5. Check Consecutive Loss Counter
curl http://localhost:8010/v1/safety/loss-tracker
# Look for: "consecutive_losses": 0 (should be reset after 24 hours of no new losses)

# 6. Confirm Kill Switch Status
curl http://localhost:8010/v1/safety/kill-switch
# Expected: "kill_switch_active": false, "reason": "manual"

# 7. Review System Resources
docker stats --no-stream
# Memory usage should be < 1GB, CPU < 30%
```

### 4.2 During Trading Session (Market Hours)

**Monitoring Interval:** Every 30 minutes

```bash
# 1. Monitor Kill Switch Status
#    If it ever becomes ACTIVE (red badge on dashboard), STOP and investigate immediately
curl http://localhost:8010/v1/safety/kill-switch

# 2. Check P&L Against Daily Limits
curl http://localhost:8010/v1/trading/pnl
# If P&L < -2% of account: Kill Switch MUST activate (safety layer)
# If P&L approaches limit: Review open positions and close if needed

# 3. Verify Signal Generation is Happening
curl http://localhost:8010/v1/backtest/signals?symbols=MES,MGC&limit=5
# Should see new signals every cycle (typically every 1-5 minutes)
# Note: only MES and MGC trade (active paper since 2026-05-24); MCL/MNQ halted, M2K rejected

# 4. Monitor Agent Pipeline Latency
curl http://localhost:8010/llm/stats
# Pipeline latency should be < 30 seconds per cycle
# If > 30 seconds: LLM API may be slow or tokens exhausted

# 5. Check for Order Submission Logs (Paper Trading Mode)
tail -n 20 engine/logs/jarvis.log | grep -i "order\|submitted\|paper"
# Should see logs like: "Order simulated (PAPER_TRADING=True): BUY 1 MES @ market"
```

### 4.3 Evening Routine (After Market Close)

**Time:** 30 minutes after market close (e.g., 4:00 PM EST)

```bash
# 1. Generate Daily Statistics Report
curl http://localhost:8010/v1/trading/daily-summary?date=2026-04-01
# Review: total trades, win rate, P&L, Sharpe ratio

# 2. Review All Today's Agent Decisions
curl http://localhost:8010/v1/agents/decisions?date=2026-04-01
# Analyze each decision: Was reasoning sound? Did safety layer behave correctly?

# 3. Check Consecutive Loss Counter State
curl http://localhost:8010/v1/safety/loss-tracker
# If trades were losers: note "consecutive_losses" count

# 4. Verify All Errors Were Logged
grep -i "error\|exception\|critical" engine/logs/jarvis.log | tail -n 50
# Every error must be understood and documented

# 5. Archive Daily Logs
mkdir -p engine/logs/archive/2026-04-01
cp engine/logs/jarvis.log engine/logs/archive/2026-04-01/
# Keep daily snapshots for post-mortem analysis if needed

# 6. Review Dashboard Metrics
#    Screenshot or note: Sharpe ratio, max drawdown, win rate
#    Compare against success criteria (Section 5)
```

---

## Section 5: 30-Day Forward Test Success Criteria

JARVIS TRADER must meet ALL criteria below to qualify for live trading. These are NOT targets; they are REQUIREMENTS.

### 5.1 Profitability Metrics

| Metric | Requirement | Rationale |
|--------|-------------|-----------|
| **Profit Factor (PF)** | > 1.5 | Gross profit ÷ Gross loss. Backtest achieved 5.27 PF; 1.5 is relaxed to account for live slippage and 24/7 market conditions. |
| **Sharpe Ratio** | > 1.0 | Risk-adjusted return. Measures consistency of returns relative to volatility. |
| **Max Drawdown** | < 10% | Matches safety layer limit. Drawdown should never exceed emergency halt threshold. |
| **Win Rate** | > 45% | Percentage of profitable trades. Validates signal generation quality. |

### 5.2 System Health Metrics

| Metric | Requirement | Rationale |
|--------|-------------|-----------|
| **Agent Pipeline Latency** | < 30 seconds | Per-cycle latency. > 30s may miss entry points or cause stale signals. |
| **Broker Uptime** | 99.5% | IB Gateway connection availability. Gaps > 5 minutes require investigation. |
| **Data Feed Freshness** | < 2 seconds | Quote age must be < 2 seconds old. Older data triggers kill switch. |
| **Unhandled Exceptions** | 0 in 30 days | Zero crashes. All exceptions must be caught and logged gracefully. |

### 5.3 Safety Layer Validation

| Scenario | Expected Behavior | Validation Method |
|----------|------------------|-------------------|
| **Daily Loss Hits -6%** | Kill Switch auto-activates | Monitor P&L; trigger manually if needed |
| **Drawdown Hits -20%** | Kill Switch auto-activates | Monitor max drawdown in dashboard |
| **Consecutive Losses (7)** | Position size auto-reduced (first 5 losses) then halt | Induce losses; verify position sizing |
| **Order Rate > 10/min** | Orders throttled; oldest dropped | Stress test with high-frequency signal burst |
| **Price Collar Violation** | Order rejected (logged) | Submit orders > 5% away from NBBO |

### 5.4 Paper Trading Mode Validation

| Requirement | Validation Method |
|-------------|-------------------|
| **Orders logged but NOT sent to broker** | Confirm in logs: "Order simulated (PAPER_TRADING=True): ..." |
| **No real money at risk** | Confirm in dashboard: "Paper Trading Mode" badge visible |
| **IBKR balance unchanged after 30 days** | Screenshot starting balance vs. final balance (should match) |
| **Kill Switch prevents any broker submission** | Activate kill switch; confirm orders are rejected |

### 5.5 Success Declaration

The 30-day test is **COMPLETE AND SUCCESSFUL** when:

1. All profitability metrics (Section 5.1) are met
2. All system health metrics (Section 5.2) are met
3. All safety layer validations (Section 5.3) passed
4. All paper trading mode validations (Section 5.4) passed
5. Zero critical bugs found that require code changes
6. Matt reviews and approves the results

**If ANY metric is missed:** Extend paper testing by 15-30 days, diagnose root cause, and re-test.

---

## Section 6: Kill Switch Verification

The Kill Switch is the emergency stop mechanism. It must work correctly 100% of the time.

### 6.1 Manual Kill Switch Activation

```bash
# Method 1: Via API
curl -X POST http://localhost:8010/v1/safety/kill-switch/activate \
  -H "X-API-Key: jarvis-dev-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"reason": "manual_test"}'

# Expected response:
# {
#   "kill_switch_active": true,
#   "reason": "manual_test",
#   "timestamp": "2026-04-01T14:30:00Z"
# }

# Method 2: Via Dashboard
# Click red "Kill Switch" button at top-right of dashboard
```

### 6.2 Kill Switch Verification Checklist

After activation, verify:

```bash
# 1. Kill Switch shows ACTIVE in dashboard (red badge)
curl http://localhost:8010/v1/safety/kill-switch
# Expected: "kill_switch_active": true

# 2. Orders are REJECTED (not submitted to broker)
# Try to submit an order via API — should be blocked with reason: "Kill Switch Active"
curl -X POST http://localhost:8010/v1/trading/submit-order \
  -H "X-API-Key: jarvis-dev-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "MES", "quantity": 1, "order_type": "market"}'
# Expected response: { "error": "Kill Switch is active. All orders rejected." }

# 3. Check logs for kill switch rejection
grep "Kill Switch" engine/logs/jarvis.log | tail -n 5

# 4. Agent pipeline stops generating new signals
# Dashboard should show: "Agent Status: Paused (Kill Switch Active)"
```

### 6.3 Kill Switch Recovery Procedure

To re-arm trading after kill switch activation:

```bash
# 1. Review the Reason for Kill Switch Activation
curl http://localhost:8010/v1/safety/kill-switch
# Identify: daily_loss_limit, max_drawdown, manual, etc.

# 2. If Manual: Rearm Immediately
curl -X POST http://localhost:8010/v1/safety/kill-switch/rearm \
  -H "X-API-Key: jarvis-dev-key-change-me" \
  -H "Content-Type: application/json"

# 3. If Automatic (Daily Loss or Drawdown): Wait for Recovery
# Daily Loss: Kill switch auto-rearms next trading day (UTC midnight)
# Max Drawdown: Manual rearm only (requires review by Matt)
#
# To force rearm (only if root cause identified and fixed):
curl -X POST http://localhost:8010/v1/safety/kill-switch/rearm \
  -H "X-API-Key: jarvis-dev-key-change-me" \
  -d '{"verified_by": "matt_trader", "root_cause": "..."}'

# 4. Verify Kill Switch is now DISARMED
curl http://localhost:8010/v1/safety/kill-switch
# Expected: "kill_switch_active": false
```

### 6.4 Kill Switch Testing Checklist

Test kill switch functionality before live trading:

```bash
# Test 1: Manual Activation
# [ ] Kill switch activates immediately
# [ ] Dashboard shows red badge
# [ ] Orders are rejected with proper message
# [ ] Logs contain activation reason

# Test 2: Manual Rearm
# [ ] Kill switch rearms successfully
# [ ] Dashboard shows green badge (ARMED for trading)
# [ ] Orders are accepted again

# Test 3: Automatic Activation (Daily Loss)
# [ ] Simulate losing trades that hit -2% threshold
# [ ] Kill switch must auto-activate (no manual action needed)
# [ ] Verify reason in logs: "daily_loss_limit"

# Test 4: Automatic Activation (Drawdown)
# [ ] Simulate consecutive losses that hit -10% from peak
# [ ] Kill switch must auto-activate
# [ ] Verify reason in logs: "max_drawdown"

# Test 5: Consecutive Loss Recovery
# [ ] Verify position sizing is reduced after 3 consecutive losses
# [ ] Verify position sizing is quarter-size after 5 losses
# [ ] Verify trading halts after 7 consecutive losses
```

---

## Section 7: Rollback Procedure

If critical bugs are discovered during the 30-day paper test that require code changes:

### 7.1 Bug Discovery and Triage

```bash
# 1. Immediately activate kill switch
curl -X POST http://localhost:8010/v1/safety/kill-switch/activate \
  -H "X-API-Key: jarvis-dev-key-change-me" \
  -d '{"reason": "critical_bug_found"}'

# 2. Capture full context
cp -r engine/logs engine/logs.backup.$(date +%s)
cp engine/.env engine/.env.backup.$(date +%s)

# 3. Get detailed error information
tail -n 200 engine/logs/jarvis.log > bug_report_initial.txt

# 4. Identify which component is broken
# Is it: Agent pipeline, Signal generation, Safety layer, Broker connector?
grep "error\|exception\|traceback" engine/logs/jarvis.log | tail -n 20 >> bug_report_initial.txt
```

### 7.2 Source Identification (git bisect)

If the bug was introduced by a recent code change:

```bash
# 1. Identify last known-good commit
git log --oneline -10

# 2. Start bisect (if commit history exists)
git bisect start
git bisect bad HEAD  # Current commit is buggy
git bisect good <last_known_good_commit>

# 3. Test each commit
# The bisect process will checkout each commit
# Run paper trading tests and mark as good/bad
# After each test:
git bisect good
# or
git bisect bad

# 4. Identify the regression commit
git bisect log
```

### 7.3 Emergency Rollback

If the bug cannot be quickly fixed:

```bash
# 1. Stop all JARVIS services
pkill -f "uvicorn main"
pkill -f "health_monitor"
pkill -f "npm run dev"
pkill -f "docker-compose"

# 2. Revert to last stable commit
git checkout <last_known_good_commit>

# 3. Restart JARVIS
start_jarvis.bat  # Windows
# or on macOS/Linux:
# (restart the services manually)

# 4. Verify kill switch was not disarmed
curl http://localhost:8010/v1/safety/kill-switch
# Should show: "kill_switch_active": true (from previous emergency activation)
```

### 7.4 Post-Mortem Template

Document all bugs found for future prevention:

```markdown
# Bug Report: [Date]

## Summary
- **Bug:** [One-line description]
- **Severity:** Critical / Major / Minor
- **Detected:** [Date & Time]
- **Duration:** [How long was it in production]

## Impact
- **Positions affected:** [None / specific trades]
- **P&L impact:** [Amount, if any]
- **Safety layer response:** [Did kill switch trigger? Why/why not?]

## Root Cause
- **Component:** [Agent / Signal / Safety / Broker]
- **Code location:** [File & line number]
- **Commit:** [Git commit that introduced bug]

## Resolution
- **Fix:** [Code change made]
- **Testing:** [How was fix validated]
- **Time to fix:** [Hours to resolution]

## Prevention
- **Test added:** [Yes / No] What test would catch this?
- **Documentation:** [What doc needs updating]
- **Monitor:** [New metric to track]
```

---

## Section 8: Graduation to Live Trading

After the 30-day paper test successfully completes, the system is ready for live trading. This section documents the transition process.

### 8.1 Live Trading Readiness Checklist

Before ANY live money goes at risk, verify:

- [ ] All success criteria from Section 5 are met
- [ ] All bug reports from Section 7 have been resolved
- [ ] Kill switch has been tested at least 5 times (activations + rearms)
- [ ] All agent types (analyst, trader, risk, fund manager) have been tested
- [ ] Signal generation is consistent and repeatable
- [ ] No new errors in the last 7 days of paper testing
- [ ] Dashboard displays all metrics correctly
- [ ] Backtest and forward test results are saved and documented

### 8.2 Configuration Changes for Live Trading

To transition from paper to live, these configuration changes MUST be made:

```bash
# 1. Edit engine/.env

# CHANGE: Paper Trading Mode
# FROM:
PAPER_TRADING=True

# TO:
PAPER_TRADING=False

# CHANGE: IB Gateway Port (paper → live)
# FROM:
IBKR_PORT=7497

# TO:
IBKR_PORT=7496

# VERIFY: These must also be correct
LIVE_TRADING_ENABLED=True
REQUIRE_HUMAN_APPROVAL=True  # Keep True for first week

# 2. Restart Engine
# The config validation will ensure PAPER_TRADING=False requires SCHWAB_READY=True
# If Schwab connector is not ready, startup will fail with clear error message
```

### 8.3 Position Sizing Reduction (First Week)

For the first 5 trading days on live account:

- **Week 1 (Days 1-5):** 0.25x position size (quarter of backtested size)
- **Week 2 (Days 6-10):** 0.50x position size (half of backtested size)
- **Week 3+ (Days 11+):** 1.00x position size (full backtested size)

```python
# This is implemented in engine/risk/position_sizing.py
# No code changes needed; just set these env vars:

LIVE_TRADING_WEEK_1=True  # Triggers 0.25x multiplier
# After 5 days:
LIVE_TRADING_WEEK_1=False
LIVE_TRADING_WEEK_2=True  # Triggers 0.50x multiplier
# After 10 days:
LIVE_TRADING_WEEK_2=False
# (Full position size now)
```

### 8.4 Extra Monitoring During Live Transition

During the first 2 weeks on live account, increase monitoring frequency:

```bash
# Monitoring frequency: EVERY 15 MINUTES (vs 30 minutes in paper test)

# Every 15 min: Check kill switch and P&L
for i in {1..100}; do
  echo "Check $(date)"
  curl http://localhost:8010/v1/safety/kill-switch
  curl http://localhost:8010/v1/trading/pnl
  sleep 900  # 15 minutes
done

# Every 4 hours: Review all decisions and log analysis
# Every day: Review daily summary report and compare to paper test results

# At day 5: Transition from 0.25x to 0.50x position size
# At day 10: Transition from 0.50x to 1.00x position size
```

### 8.5 Failure Recovery (Live Trading)

If live trading encounters a critical bug:

```bash
# 1. IMMEDIATELY activate kill switch
curl -X POST http://localhost:8010/v1/safety/kill-switch/activate \
  -H "X-API-Key: jarvis-dev-key-change-me" \
  -d '{"reason": "critical_bug_live_trading"}'

# 2. Close all open positions manually via IBKR
#    DO NOT rely on automated close — verify via IBKR web interface
#    Risk Management Phone: [call IBKR support for immediate assistance]

# 3. Capture logs
cp -r engine/logs engine/logs.live_incident.$(date +%s)

# 4. Halt and investigate
# Follow Section 7 Rollback Procedure

# 5. After fix is deployed and tested (in paper mode again):
#    - Run paper test for 5 additional days
#    - Address root cause with code changes AND tests
#    - Only then restart live trading
```

### 8.6 Live Trading Success Metrics

After transitioning to live, JARVIS TRADER is considered "successful" when:

- **Month 1:** Profit Factor > 1.2, Max Drawdown < 5%, Win Rate > 50%
- **Month 2+:** Returns consistent with backtested expectations, no major drawdowns

If Month 1 live results differ significantly from paper test:
- Pause live trading (activate kill switch)
- Investigate cause (slippage, commissions, API latency, etc.)
- Adjust strategy parameters
- Re-test in paper mode before resuming

---

## Appendix A: Troubleshooting

### Engine Won't Start

**Symptom:** `[ERROR] Engine health check failed`

**Diagnostics:**
```bash
# Check Python dependencies
cd engine
python -m pip install -r requirements.txt

# Test individual imports
python -c "from config import settings; print('Config OK')"
python -c "from main import app; print('Main OK')"

# Check logs
tail -n 50 logs/jarvis.log
```

**Common Causes:**
- Missing .env file → Create from .env.example
- Invalid API keys → Verify in .env
- Database not running → `docker-compose up -d`
- Port 8010 already in use → `lsof -i :8010` then kill process

### IB Gateway Connection Fails

**Symptom:** `[ERROR] IB Gateway connection refused`

**Diagnostics:**
```bash
# Check IB Gateway is running
lsof -i :7497
# If empty, IB Gateway is not running

# Test port connectivity
nc -zv 127.0.0.1 7497

# Check IB Gateway logs
cat ~/IBGateway/TWS.log  # Path varies by OS
```

**Common Causes:**
- IB Gateway not running → Launch manually
- Wrong port (7496 vs 7497) → Check config
- IB Gateway not logged in → Log in with IBKR credentials
- Java not installed → Install Java 11+

### Agent Pipeline Latency > 30 Seconds

**Symptom:** Signals are slow to generate

**Diagnostics:**
```bash
# Check LLM API response times
curl http://localhost:8010/llm/stats | jq '.response_times'

# Check if API keys are valid
python -c "
import os
from anthropic import Anthropic
os.environ['ANTHROPIC_API_KEY'] = os.getenv('ANTHROPIC_API_KEY')
client = Anthropic()
# If this fails, API key is invalid
"

# Check network latency
ping api.anthropic.com
```

**Common Causes:**
- API key exhausted (over rate limit) → Wait 1 hour or upgrade plan
- Network latency → Check ISP connection
- LLM API overloaded → Use FAST_MODEL instead of ANALYST_MODEL

### Orders Not Submitting (Paper Mode)

**Symptom:** Trades are generated but logs show no orders

**Diagnostics:**
```bash
# Check if PAPER_TRADING is True (should be)
curl http://localhost:8010/v1/system/config | grep PAPER_TRADING

# Check kill switch is not active
curl http://localhost:8010/v1/safety/kill-switch

# Review signal generation
curl http://localhost:8010/v1/backtest/signals?symbols=MES&limit=5

# Check logs for order rejection reasons
grep -i "order\|rejected\|blocked" engine/logs/jarvis.log | tail -n 20
```

**Common Causes:**
- Kill switch is active → Rearm it
- Price collar violation → Adjust order price
- Position size exceeds MAX_POSITION_SIZE_PCT → Risk layer rejected it
- PAPER_TRADING=False but SCHWAB_READY=False → Fix config

---

## Appendix B: References

- **IBKR API Documentation:** https://interactivebrokers.com/en/trading/platforms/ib-gateway.php
- **IB Gateway Download:** https://www.interactivebrokers.com/en/trading/platforms/ib-gateway.php
- **Java Download:** https://www.oracle.com/java/technologies/downloads/
- **JARVIS TRADER Architecture:** See engine/README.md
- **Safety Layer Design:** See engine/risk/README.md
- **Agent Pipeline:** See engine/agents/README.md

---

**Document Version:** 1.0 | **Last Updated:** April 2026 | **Author:** JARVIS TRADER Dev Team
