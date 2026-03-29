# JARVIS TRADER — Paper Trading Guide

**Status**: Backtesting complete. Moving to paper trading phase.
**Engine**: FastAPI on port 8010 | **Dashboard**: Next.js on port 3010
**Last updated**: 2026-03-29

---

## 1. Pre-Paper-Trading Checklist

Complete every item in this list before running your first paper trade. Do not skip or reorder steps.

### 1.1 IBKR Account Setup

- [ ] **Open an IBKR account** at https://www.interactivebrokers.com
  - Individual account is sufficient to start
  - Paper trading account is activated automatically after account approval
  - Paper trading uses a simulated $1,000,000 portfolio by default (can be reset)

- [ ] **Download IB Gateway** (preferred over full TWS for headless use)
  - URL: https://www.interactivebrokers.com/en/trading/ibgateway.php
  - IB Gateway is lighter than TWS and better suited for automated connections
  - Alternatively, use Trader Workstation (TWS) if you prefer the full UI

- [ ] **Log in to paper trading mode**
  - Launch IB Gateway
  - At the login screen, select "Paper Trading" from the account type dropdown
  - Use your IBKR username and password (same credentials, different account type)

### 1.2 IB Gateway / TWS API Configuration

Once logged in to paper trading mode, configure the API settings:

1. Open **Configure** menu -> **Settings** (IB Gateway) or **Edit** -> **Global Configuration** (TWS)
2. Navigate to **API** -> **Settings**
3. Enable the following:
   - [x] **Enable ActiveX and Socket Clients**
   - [x] **Allow connections from localhost only** (security best practice)
   - Socket port: **4002** (this is already configured in `engine/.env` as `IBKR_PORT=4002`)
   - Master Client ID: **1** (matches `IBKR_CLIENT_ID=1` in `engine/config.py`)
4. Click **OK** and restart IB Gateway if prompted

**Port reference** (from `engine/execution/ibkr_executor.py`):
```
Port 4002 = Paper trading  <-- USE THIS
Port 4001 = Live trading   <-- DO NOT USE until go/no-go criteria are met
```

The executor detects the mode automatically based on port:
```python
mode = "PAPER" if settings.IBKR_PORT == 4002 else "LIVE"
```

### 1.3 ib_async Connection Test

Before starting the full engine, verify the connection independently:

```bash
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv/Scripts/python -c "
import asyncio
from ib_async import IB

async def test():
    ib = IB()
    await ib.connectAsync('127.0.0.1', 4002, clientId=99)
    print('Connected. Server version:', ib.client.serverVersion())
    accounts = ib.managedAccounts()
    print('Accounts:', accounts)
    ib.disconnect()
    print('Disconnected cleanly.')

asyncio.run(test())
"
```

Expected output:
```
Connected. Server version: <some number>
Accounts: ['DU<your paper account number>']
Disconnected cleanly.
```

If you see `ConnectionRefusedError`: IB Gateway is not running or API is not enabled on port 4002.

### 1.4 Engine Safety Settings Verification

Confirm these values are set in `engine/.env` before first run:

```env
LIVE_TRADING_ENABLED=False      # Paper mode — no real orders
REQUIRE_HUMAN_APPROVAL=True     # All signals require manual confirmation
IBKR_PORT=4002                  # Paper trading port
IBKR_PAPER_MODE=True            # Belt-and-suspenders paper flag
```

These settings map to `engine/config.py` (`TradingConfig`). The safety layer reads them at startup and logs the active mode:

```
JARVIS TRADER starting up...
   Live trading: DISABLED (paper mode)
   IBKR port:   4002 (paper)
```

If you see `ENABLED` or port `4001` at startup — stop and fix before proceeding.

### 1.5 Pre-Flight Verification Summary

| Item | Status |
|------|--------|
| IBKR paper account open | [ ] |
| IB Gateway installed and running on port 4002 | [ ] |
| API enabled in IB Gateway settings | [ ] |
| ib_async connection test passes | [ ] |
| `LIVE_TRADING_ENABLED=False` confirmed | [ ] |
| `REQUIRE_HUMAN_APPROVAL=True` confirmed | [ ] |
| WhatsApp alerts tested and working | [x] Twilio configured |
| Backtest confirmed — SPY (22 trades, PF 4.17, Sharpe 3.95) | [x] Done |
| Backtest confirmed — MES (proxy complete) | [x] Done |
| Backtest confirmed — MNQ | [ ] Pending US-003 |

---

## 2. Daily Operating Procedure

### 2.1 Morning Startup (Before Market Open — 8:30 AM CT Target)

**Step 1 — Start IB Gateway**
Launch IB Gateway and log in to paper trading mode. Wait for the connection indicator to show green.

**Step 2 — Start the engine**
```bash
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv/Scripts/python -m uvicorn main:app --reload --port 8010
```

Watch for this in the startup output:
```
JARVIS TRADER starting up...
   Live trading: DISABLED (paper mode)
   IBKR port:   4002 (paper)
```

**Step 3 — Start the dashboard**
In a second terminal:
```bash
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard
npm run dev
```
Dashboard runs at http://localhost:3010

**Step 4 — Verify health endpoint**
```bash
curl http://localhost:8010/health
```
Expected: `{"status": "ok", ...}` with 200 response.

**Step 5 — Review overnight signals**
Open the dashboard at http://localhost:3010 and check:
- Any signals generated since last session
- Current positions (should be flat overnight unless overnight holds are expected)
- Kill switch status (must be inactive)

**Step 6 — Check WhatsApp**
Review your WhatsApp for any alerts sent overnight. The engine sends alerts for:
- Signal generation
- Order approvals pending human confirmation
- Kill switch activations
- Daily P&L summaries

### 2.2 End-of-Day Shutdown

1. Ensure all intraday positions are closed (the engine respects `MAX_OVERNIGHT_CONTRACTS=1` from config, but verify manually during paper trading)
2. Note the day's P&L and signal count in your trading journal
3. Stop the engine with Ctrl+C
4. Stop the dashboard with Ctrl+C
5. You may leave IB Gateway running or close it

---

## 3. What to Monitor During Paper Trading

### 3.1 P&L Tracking

Track these metrics daily. The dashboard pulls them from `IBKRExecutor.get_account_summary()`:

| Metric | Source | Target |
|--------|--------|--------|
| Daily P&L | `daily_pnl` from IBKR account summary | Positive on >50% of days |
| Unrealized P&L | `unrealized_pnl` | Watch for runaway drawdowns |
| Available funds | `available_funds` | Should not drop below 60% of starting equity |
| Total equity | `total_equity` (net liquidation) | Track peak for drawdown calc |

Build a simple spreadsheet: date, starting equity, ending equity, daily P&L, number of signals, number of trades taken. After 30 days this becomes your go/no-go dataset.

### 3.2 Signal Frequency

The pipeline runs for MES, MNQ, and MCL on the `FUTURES_WATCHLIST`. Watch for:

- **Too many signals (>5/day)**: Likely overfitting. The backtested Sharpe of 3.95 assumed ~22 trades over the full backtest period. If signals are firing much more frequently in live market conditions, the technical indicators may be generating false positives. Review `engine/agents/technical_analyst.py` parameters.

- **Too few signals (<1/week)**: Regime mismatch. Check whether current VIX levels or trend conditions differ significantly from your backtest period. The system may be correctly filtering — or the thresholds may need adjustment after optimization (US-005 still pending).

- **Signal clustering**: Multiple signals on the same instrument within hours often indicates noise. The correlated exposure limit (`MAX_CORRELATED_EXPOSURE_PCT=0.20`) should throttle this automatically, but monitor manually.

### 3.3 Slippage Estimation

Paper trading with IBKR simulates fills at bid/ask mid. Real-world slippage will be worse. Track the difference between:

- Signal entry price (price at signal generation time)
- Simulated fill price (what IBKR paper account reports)

For micro futures, expect 0.25–1.0 tick of slippage per side in real trading. If simulated P&L relies on fills tighter than the bid/ask spread, the live results will underperform.

Log slippage per trade and calculate average. If average slippage per round trip exceeds 1 tick on MES (= $1.25) or MNQ (= $0.50), factor this into your go/no-go evaluation.

### 3.4 Agent Veto Analysis

The pipeline runs: Technical + News + Social + Fundamental -> Bull/Bear Debate -> Trade Decision -> Risk Review -> Fund Manager.

Log which agent vetoes trades most frequently. Check engine logs for lines like:
```
Order REJECTED by SafetyLayer — reason=<reason>
```

Common rejection reasons and what they mean:

| Rejection Reason | Meaning | Action |
|-----------------|---------|--------|
| `max_position_size_pct` exceeded | Position would be >5% of equity | Normal — reduce size or skip |
| `max_daily_loss_pct` breached | Already down >2% today | Kill switch territory — correct behavior |
| `max_single_order_value` exceeded | Order > $5,000 | Normal for micro futures sizing |
| `kill_switch_active` | Emergency halt engaged | Investigate cause immediately |
| `BROKER_DISCONNECT` | IB Gateway lost connection | Check IB Gateway status |

If the Risk Manager or Fund Manager agents are vetoing >40% of Trade Decision recommendations, the agent personas may be calibrated too conservatively. This is better than being too aggressive during paper trading.

### 3.5 VIX Regime Correlation

Track the VIX level each day alongside your signal quality:

| VIX Range | Expected Behavior |
|-----------|------------------|
| VIX < 15 | Low volatility — signals may be sparse, mean-reversion setups common |
| VIX 15–25 | Normal range — system was primarily backtested here |
| VIX 25–35 | Elevated — trend signals more reliable, stops must be wider |
| VIX > 35 | Crisis regime — consider manual override/pause, kill switch ready |

The backtested results (SPY daily, Sharpe 3.95, PF 4.17) were generated against 2025 data. If current VIX regime differs substantially, expect performance divergence. This is normal and expected. Do not tune parameters during paper trading based on short-term results — wait for the full 30-day sample.

---

## 4. IBKR TWS / IB Gateway Technical Setup

### 4.1 How the API Connection Works

JARVIS TRADER connects to IBKR via `ib_async`, which wraps the IB TWS API over a persistent TCP socket. The connection is managed by `IBKRExecutor` in `engine/execution/ibkr_executor.py`.

Connection parameters (set in `engine/config.py` and overridden via `engine/.env`):

```python
IBKR_HOST: str = "127.0.0.1"    # Always localhost for local setup
IBKR_PORT: int = 4002            # 4002 = paper, 4001 = live
IBKR_CLIENT_ID: int = 1          # Must be unique per simultaneous connection
```

The executor auto-detects paper vs. live mode by port:
```python
mode = "PAPER" if settings.IBKR_PORT == 4002 else "LIVE"
```

### 4.2 Reconnection Behavior

The executor handles disconnections automatically:
- Max reconnect attempts: **3**
- Delay between attempts: **5 seconds**
- If all attempts fail: **kill switch activates** with reason `BROKER_DISCONNECT`

This means if IB Gateway crashes or disconnects during market hours, the engine will halt trading automatically. You will receive a WhatsApp alert. To resume: restart IB Gateway, then restart the engine.

### 4.3 Paper vs. Live Mode Switching

When you are eventually ready to go live, the switch requires two changes in `engine/.env`:

```env
# Paper trading (current)
IBKR_PORT=4002
IBKR_PAPER_MODE=True
LIVE_TRADING_ENABLED=False

# Live trading (DO NOT SET until go/no-go criteria are met)
IBKR_PORT=4001
IBKR_PAPER_MODE=False
LIVE_TRADING_ENABLED=True
```

Additionally, log in to IB Gateway with your **live** account credentials (not paper mode). The engine does not manage the IB Gateway login — you must do this manually.

Do not switch to live until every criterion in Section 5 is met.

### 4.4 Supported Instruments and Exchanges

The executor supports these micro futures contracts (from `ibkr_executor.py`):

| Symbol | Exchange | Description |
|--------|----------|-------------|
| MES | CME | Micro E-mini S&P 500 |
| MNQ | CME | Micro E-mini Nasdaq-100 |
| M2K | CME | Micro Russell 2000 |
| MCL | NYMEX | Micro Crude Oil |
| MGC | COMEX | Micro Gold |
| MHG | COMEX | Micro Copper |
| MSI | CME | Micro Silver |

Active watchlist from `config.py`: `["MES", "MNQ", "MCL"]`

### 4.5 Contract Month Logic

The executor automatically selects the nearest active quarterly expiry (March, June, September, December). You do not need to manage contract rolls manually. The `_nearest_quarterly_expiry()` function handles this using today's date.

If you are trading near expiry (within a week of the third Friday of an expiry month), monitor the contract month being selected and verify it matches the front-month contract shown in IB Gateway.

### 4.6 Safety Layer — What It Enforces

Every order passes through `SafetyLayer.check_order()` before reaching IBKR. There is no bypass path. The active risk limits from `config.py`:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `MAX_POSITION_SIZE_PCT` | 5% | Max per-position size as % of equity |
| `MAX_DAILY_LOSS_PCT` | 2% | Halt trading at -2% daily P&L |
| `MAX_DRAWDOWN_PCT` | 10% | Emergency halt at -10% from equity peak |
| `MAX_ORDERS_PER_MINUTE` | 10 | Rate throttle |
| `MAX_SINGLE_ORDER_VALUE` | $5,000 | No single order above this |
| `MAX_MARGIN_UTILIZATION` | 40% | Max margin usage |
| `MAX_CONTRACTS_PER_INSTRUMENT` | 2 | Max micro contracts per instrument |
| `MAX_OVERNIGHT_CONTRACTS` | 1 | Max contracts held overnight |
| `PRICE_COLLAR_PCT` | 5% | Reject orders >5% from NBBO |

These limits are conservative and appropriate for paper trading. Do not loosen them before completing 30 days of paper trading.

---

## 5. Live Trading Go/No-Go Criteria

Matt must meet **ALL** of the following criteria before switching `LIVE_TRADING_ENABLED=True`. No exceptions.

### 5.1 Minimum Criteria

| Criterion | Target | How to Measure |
|-----------|--------|---------------|
| Paper trading duration | 30 calendar days minimum | First paper trade date to evaluation date |
| Paper trade count | At least 20 completed round trips | Count from engine logs or dashboard trade history |
| Paper Sharpe ratio | >= 2.0 | Annualized Sharpe on paper trading P&L series |
| Paper max drawdown | < 5% of starting paper equity | Max peak-to-trough on paper equity curve |
| Engine uptime | >= 95% during market hours | Measured against 6.5 hours/day × trading days |
| Kill switch activations | Zero unexplained activations | Investigate any kill switch event before proceeding |
| WhatsApp alert delivery | 100% of tested alerts delivered | Send test alerts; verify delivery within 60 seconds |
| IB Gateway stability | Zero unrecovered disconnects | Reconnect logic must have recovered all disconnects automatically |

### 5.2 Qualitative Criteria

Before going live, also confirm:

- You understand every agent in the pipeline and what it does
- You have read and can explain every rejection reason the safety layer produces
- You have a written emergency procedure: what you do if the kill switch fires during live trading with open positions
- You have set a maximum live trading loss limit for yourself (e.g., stop live trading if you lose more than $500 real money in any 30-day period) — this is separate from the engine's automated limits
- You have verified your IBKR live account has sufficient margin for at least 2 MES contracts ($1,320+ initial margin per contract as of 2026, check current IBKR margin requirements)

### 5.3 Going Live Procedure (When Criteria Are Met)

1. Stop the engine
2. Update `engine/.env`:
   ```env
   IBKR_PORT=4001
   IBKR_PAPER_MODE=False
   LIVE_TRADING_ENABLED=True
   ```
3. Log in to IB Gateway with **live account** (not paper)
4. Start the engine
5. Verify startup log shows: `Live trading: ENABLED` and `IBKR port: 4001 (live)`
6. Keep `REQUIRE_HUMAN_APPROVAL=True` for the first 5 live trades
7. After 5 approved live trades with expected behavior, you may evaluate setting `REQUIRE_HUMAN_APPROVAL=False` for fully autonomous operation

**Recommended**: Keep `REQUIRE_HUMAN_APPROVAL=True` indefinitely for the first month of live trading. The WhatsApp approval flow adds at most a few seconds of latency, which is acceptable for the micro futures timeframes this system trades.

---

## 6. Troubleshooting Quick Reference

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `ib_async is not installed` at startup | Missing pip dependency | `pip install ib_async` in the venv |
| `ConnectionRefusedError` on connect | IB Gateway not running or API not enabled | Start IB Gateway, check port 4002 API setting |
| Kill switch fires immediately at startup | BROKER_DISCONNECT after 3 failed reconnects | Verify IB Gateway is running before starting engine |
| No signals generated | Market closed or instruments not in session | Check market hours; CME Globex runs nearly 24h but has brief daily halt |
| Signal generated but no WhatsApp | Twilio credentials missing or sandbox not joined | Verify `.env` has `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `WHATSAPP_TO` |
| `Contract qualification failed` | IBKR does not recognize the contract spec | Check contract month vs. front month in IB Gateway; may be near roll date |
| Dashboard shows no data | Engine not running or CORS issue | Confirm engine is on port 8010 and dashboard on port 3010 |

---

*JARVIS TRADER — Paper Trading Guide | Engine v0.1 | Generated 2026-03-29*
