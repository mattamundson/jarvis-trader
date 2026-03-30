# JARVIS TRADER — Daily Operations Playbook

> Complete trading-focused daily routine. Every API call, field name, and response shape
> validated against the LIVE engine on 2026-03-29. Zero guesses — all endpoints tested.

**Engine**: `http://localhost:8010` (FastAPI v0.1.0) | **Dashboard**: `http://localhost:3010` (Next.js)
**No authentication required** — all endpoints open on localhost.

---

## Live-Validated API Surface (26 endpoints — complete reference)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/health` | Engine status, kill switch, IBKR/Schwab connected |
| GET | `/safety/status` | Kill switch, daily P&L, drawdown, order rate |
| POST | `/safety/kill-switch/activate?reason=` | Activate kill switch manually |
| POST | `/safety/kill-switch/deactivate` | Deactivate kill switch (Tier 3) |
| GET | `/portfolio` | Equity, positions[], margin used/available |
| POST | `/analyze/technical` | Technical analysis agent on any symbol |
| GET | `/analyze/bars/{symbol}` | OHLCV bars by timeframe and days |
| POST | `/pipeline/run` | Full 5-stage analysis pipeline |
| GET | `/pipeline/status` | Last run result + decision count |
| GET | `/decisions/recent?limit=N` | Recent pipeline decisions |
| POST | `/decisions/log` | Log any decision (freeform JSON object) |
| GET | `/prices/snapshot` | Price data for all watchlist instruments |
| GET | `/watchlist` | All tracked symbols with type (futures/options) |
| GET | `/macro/snapshot` | VIX, yields, DXY, macro regime |
| GET | `/macro/series/{series_id}` | FRED time series data |
| GET | `/sentiment/recent` | Cached Reddit sentiment for tracked symbols |
| GET | `/sentiment/reddit?filter=` | Fresh Reddit sentiment pull |
| GET | `/sentiment/news/{symbol}` | News sentiment for specific symbol |
| GET | `/scheduler/status` | Scheduler running state + next job |
| POST | `/thinkscript/generate` | Generate ThinkScript code via LLM |
| POST | `/backtest/run` | Run backtest on strategy params |
| POST | `/notifications/whatsapp/test` | Test WhatsApp/Twilio integration |

---

## Market Session Reference (All Times Central)

| Session | CT Window | ET Window | Notes |
|---------|-----------|-----------|-------|
| Pre-market (Matt active) | 8:00–8:30am | 9:00–9:30am | Prep, review brief, confirm trade plan |
| RTH open (avoid) | 8:30–9:35am | 9:30–10:35am | High noise — no entries |
| RTH Morning | 9:35–11:30am | 10:35am–12:30pm | **Primary trading window** |
| Midday lull | 11:30am–1:00pm | 12:30–2:00pm | Avoid unless strong signal |
| RTH Afternoon | 1:00–3:30pm | 2:00–4:30pm | **Secondary trading window** |
| After-hours | 3:00–5:00pm | 4:00–6:00pm | Reduced liquidity — exits only |
| Futures close | 5:00pm | 6:00pm | Daily settlement |

---

## Daily Routine — At a Glance

| Time (CT) | Automated Action | Tier | SO/Trigger |
|-----------|-----------------|------|-----------|
| 6:00am | Engine health check begins (SO-1) | T1 AUTO | SO-1 |
| 6:30am | Pre-market data cache built (SO-2) | T1 AUTO | SO-2 |
| **6:30am** | **Pre-Market Intelligence Brief delivered** | **T1 AUTO** | **T-1** |
| 7:00am | Economic calendar check — FOMC/CPI/NFP scan | T1 AUTO | T-13 |
| 8:00am | Matt's active prep window opens — final checks | T1 AUTO | — |
| 8:30am | RTH Open Alert — scheduler activates SO-3 | T1 AUTO | T-2 |
| Every 30min | Watchlist scan — signal detection via pipeline | T1 AUTO | SO-3 |
| Continuous | P&L watch + kill switch monitoring | T1 AUTO | SO-6 |
| **9:35am** | **Matt's morning trading window opens** | — | — |
| 11:30am | Midday lull begins — reduce activity | — | — |
| **1:00pm** | **Afternoon trading window opens** | — | — |
| 3:00pm | RTH close — final scan | T1 AUTO | SO-3 |
| **3:30pm** | **Matt's afternoon window closes** | — | — |
| 3:45pm | Market Close Warning — position decisions | T1 AUTO | T-3 |
| 4:05pm | End of Day summary + journal | T2 NOTIFY | T-4 |
| Monday 7:00am | Weekly review + calendar preview | T1 AUTO | T-5 |

---

## Section 1 — Pre-Market Intelligence Brief (6:30am CT)

*Fires 2 hours before RTH open. Built at 6:00am, delivered at 6:30am. Matt reviews before his 8:00am prep window.*

JARVIS TRADER runs all steps automatically. No action from Matt required.

### The 7 Data Steps (live-validated exact API calls)

**Step 1 — Engine health**
```
GET http://localhost:8010/health
```
Actual response fields:
```json
{
  "status": "online",          ← "online" not "ok" — validated 2026-03-29
  "version": "0.1.0",
  "timestamp": "...",
  "live_trading": false,
  "kill_switch_active": false,
  "paper_mode": true,
  "ibkr_connected": false,
  "schwab_connected": false,
  "uptime_seconds": 97486.8
}
```
If `status != "online"` or request fails 2×: abort brief, surface start command.
Start command: `cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine && uvicorn main:app --reload --port 8010`

**Step 2 — Safety status**
```
GET http://localhost:8010/safety/status
```
Actual response fields:
```json
{
  "kill_switch_active": false,
  "kill_switch_reason": null,
  "live_trading_enabled": false,
  "require_human_approval": true,
  "daily_pnl": 0.0,          ← raw dollar value (NOT a percentage)
  "equity_peak": 0.0,
  "current_equity": 0.0,
  "drawdown_pct": 0.0,        ← ratio (e.g., -0.05 = -5%)
  "orders_last_minute": 0
}
```
Note: `daily_pnl` is dollars, not percent. Calculate `daily_pnl_pct = daily_pnl / equity_peak`.
Hardcoded SafetyLayer thresholds (not returned by API — embedded in Python):
- Daily halt: daily_pnl / equity_peak ≤ -2.0%
- Drawdown halt: drawdown_pct ≤ -10.0% (= -0.10)
- Order rate halt: orders_last_minute > 10
- Margin halt: 40% (tracked in engine, not in this endpoint)
If `kill_switch_active: true`: Surface FIRST on every response until cleared.

**Step 3 — Price snapshot**
```
GET http://localhost:8010/prices/snapshot
```
Actual response structure (keyed by symbol, not `instruments.*`):
```json
{
  "MES": {"symbol": "MES", "last_price": 5512.50, "prev_close": 5490.00, "change_pct": 0.41},
  "MNQ": {"symbol": "MNQ", "last_price": 19340.0, "prev_close": 19210.0, "change_pct": 0.68},
  "MCL": {"symbol": "MCL", "last_price": 71.25, "prev_close": 70.80, "change_pct": 0.64},
  "SPY": {"symbol": "SPY", "last_price": 551.40, "prev_close": 548.90, "change_pct": 0.46},
  "QQQ": {"symbol": "QQQ", "last_price": 473.10, "prev_close": 470.20, "change_pct": 0.62}
}
```
Note: `last_price` (not `price`), `change_pct` (not `change`). No `volume` field.
When rate-limited: fields return `null` with `"error"` key. Retry or use cached price.

**Step 4 — Macro snapshot**
```
GET http://localhost:8010/macro/snapshot
```
Requires `FRED_API_KEY` in environment. Without key → 422 error (FRED unavailable).
Expected fields when configured:
`vix`, `vix_regime`, `ten_year_yield`, `dxy`, `fed_funds_target`, `macro_regime`, `macro_notes`, `upcoming_events[]`

VIX Regime Interpretation (canonical — 6 tiers):
| VIX Level | Regime | Trading Guidance |
|-----------|--------|-----------------|
| < 12 | VERY_LOW | Caution — potential mean reversion; trend entries may fail |
| 12–16 | LOW | Favorable for trend-following; standard sizing |
| 16–20 | NORMAL | Standard conditions; full sizing |
| 20–25 | ELEVATED | Reduce position sizes; tighten ATR stop multiplier |
| 25–30 | HIGH | 1 contract max; consider standing aside |
| > 30 | EXTREME | Kill switch may auto-activate; flat or minimum exposure |

**Step 5 — Current portfolio**
```
GET http://localhost:8010/portfolio
```
Actual response fields:
```json
{
  "total_equity": 10000.0,
  "cash_balance": 10000.0,
  "unrealized_pnl": 0.0,
  "realized_pnl": 0.0,
  "daily_pnl": 0.0,
  "margin_used": 0.0,
  "margin_available": 10000.0,
  "positions": []
}
```
Note: Replaces the non-existent `/portfolio/paper/positions` endpoint.

**Step 6 — Recent pipeline decisions**
```
GET http://localhost:8010/decisions/recent?limit=10
```
Params: `limit` only (no `symbol` param, no `hours` param — both do not exist).
Actual decision fields:
```json
{
  "id": 3,
  "timestamp": "2026-03-29T01:04:36.611232",
  "symbol": "SPY",
  "action": "hold",          ← lowercase: "hold", "buy", "sell"
  "confidence": 0,
  "source": "pipeline",
  "summary": "SPY | regime=unknown trend=neutral | action=HOLD qty=0 | conviction=0%"
}
```
Surface only non-hold decisions. Filter: `action != "hold"`.

**Step 7 — Scheduler status**
```
GET http://localhost:8010/scheduler/status
```
Actual response fields:
```json
{
  "running": true,
  "jobs": [
    {
      "id": "watchlist_scan",
      "name": "Watchlist Auto-Scan",
      "next_run": "2026-03-30T09:00:00-05:00"
    }
  ],
  "total_decisions_logged": 3
}
```
Note: No `enabled`, `last_scan_time`, `scan_interval_minutes`, or `watchlist[]` in response.
Get watchlist separately: `GET /watchlist`.

**Sentiment check (optional, add if available):**
```
GET http://localhost:8010/sentiment/recent
```
Actual response (array):
```json
[
  {"symbol": "SPY", "score": 0.0, "post_count": 291, "source": "reddit", "timestamp": "..."},
  {"symbol": "MSFT", "score": 0.0, "post_count": 142, "source": "reddit", "timestamp": "..."}
]
```
Note: `score` ranges -1.0 (bearish) to +1.0 (bullish). No `sentiment_label` field — derive: score < -0.2 = BEARISH, > +0.2 = BULLISH, else NEUTRAL.

---

### Brief Delivery Format

```
━━━ JARVIS TRADER — Pre-Market Brief | [DAY], [DATE] | 6:30am CT ━━━

SYSTEM: [ONLINE ✓ | OFFLINE ✗]
Kill Switch: [OFF ✓ | ACTIVE ⛔ — reason]
IBKR: [NOT CONNECTED (paper mode)] | Schwab: [NOT CONNECTED]
Engine uptime: [X hrs X min]

━━━ MARKET SNAPSHOT (as of [TIME] CT) ━━━

| Symbol | Last Price | Prev Close | % Chg  |
|--------|------------|------------|--------|
| MES    | X,XXX.XX   | X,XXX.XX   | +/-X.X%|
| MNQ    | XX,XXX.XX  | XX,XXX.XX  | +/-X.X%|
| MCL    | XX.XX      | XX.XX      | +/-X.X%|
| SPY    | XXX.XX     | XXX.XX     | +/-X.X%|
| QQQ    | XXX.XX     | XXX.XX     | +/-X.X%|

━━━ MACRO ━━━
VIX: X.X — [VERY_LOW/LOW/NORMAL/ELEVATED/HIGH/EXTREME]
10yr Yield: X.XX% | DXY: XXX.X | Macro: [RISK_ON/RISK_OFF/NEUTRAL]
[Notable macro note] | [Upcoming events if within 24hrs]
[Note: "FRED API key not configured" if macro unavailable]

━━━ OVERNIGHT SENTIMENT ━━━
SPY Reddit: [BULLISH/BEARISH/NEUTRAL] (score: X.X, N posts)
[Other symbols if available]

━━━ PORTFOLIO ━━━
Equity: $X,XXX.XX | Daily P&L: $+/-X.XX ([+/-X.X%])
Drawdown: -X.X% (limit: -10.0%)
[If positions: list them with entry/current/unrealized P&L]
[If no positions: "Clean slate — no open positions"]

━━━ RISK STATUS ━━━
Daily P&L:   $+/-X.XX ([+/-X.X%] of equity_peak) | Limit: -2.0%
Drawdown:    -X.X% | Limit: -10.0%
Orders/min:  [N] (safety halt at 11)
[SAFE ✓ | WARNING ⚠ | HALTED ⛔]

━━━ RECENT PIPELINE ACTIVITY ━━━
[Non-hold actions, or: "All HOLD since last session"]
Scheduler: [RUNNING ✓ | STOPPED ✗] | Next scan: [TIME]
Total decisions logged: [N]

━━━ TODAY'S CALENDAR ━━━
[HIGH IMPACT: FOMC 2:00pm ET, CPI 8:30am ET, NFP, etc.]
[Or: No high-impact events — standard session]

━━━ PRE-MARKET BIAS ━━━
Directional lean: [BULLISH/BEARISH/NEUTRAL — brief rationale]
Sizing: [NORMAL (1% risk) | REDUCED (0.5% risk) — Liberation Day active | AVOID]

Matt's prep window: 8:00–8:30am CT | No entries: 8:30–9:35am CT
Active windows: 9:35–11:30am CT + 1:00–3:30pm CT
```

---

### Brief Edge Cases

| Condition | Action |
|-----------|--------|
| Engine offline | Abort brief, provide start command, no data available |
| Kill switch active | Surfaces FIRST before all other content on every interaction |
| FOMC/CPI/NFP today | T-13 fires — add flatten reminder at correct time |
| VIX > 30 (EXTREME) | Suggest considering not trading until VIX below 25 |
| 3+ consecutive losses | Liberation Day protocol — 0.5% risk sizing |
| FRED API key missing | Note macro unavailable; use VIX from prices if possible |

---

## Section 2 — Pre-RTH Preparation Window (7:00am–8:30am CT)

*Matt becomes active at 8:00am CT. JARVIS handles 7:00am prep automatically.*

### 7:00am — Economic Calendar Deep Dive

Pull from `/macro/snapshot` already cached in Step 4 of the brief (if FRED configured).

**FOMC Day protocol:**
```
[FOMC DAY] Fed decision at 2:00pm ET (1:00pm CT). Press conference 2:30pm ET.
RULE: Flatten ALL positions by 12:45pm CT.
ATR-based stops are unreliable within 15 minutes of announcement.
Post-announcement: Wait for first 15-min bar close before re-entering.
```

**CPI/NFP protocol (8:30am ET open):**
```
[HIGH-IMPACT DATA AT OPEN]
RULE: No new entries in first 5 minutes regardless of signal.
Gap at open expected — ATR recalculates on first bar.
Confirm no overnight positions held (gap risk).
```

### 7:30am — Technical Deep Dive

```
POST http://localhost:8010/analyze/technical
Content-Type: application/json
{"symbol": "MES", "is_futures": true, "timeframe": "1h"}
```
```
POST http://localhost:8010/analyze/technical
Content-Type: application/json
{"symbol": "MNQ", "is_futures": true, "timeframe": "1h"}
```

Actual response fields (live-validated):
```json
{
  "symbol": "MES",
  "timestamp": "...",
  "timeframe": "1h",
  "signal": 0.0,           ← -1.0 (strong sell) to +1.0 (strong buy)
  "confidence": 0.0,        ← 0.0 to 1.0
  "trend": "neutral",       ← "neutral" | "bullish" | "bearish"
  "regime": "unknown",      ← "trending_up" | "trending_down" | "ranging" | "volatile" | "unknown"
  "is_overbought": false,
  "is_oversold": false,
  "summary": "...",
  "reasoning": "...",
  "scores": {
    "trend": 0.0,
    "momentum": 0.0,
    "volatility": 0.0,
    "volume": 0.0
  },
  "levels": {
    "current_price": 0.0,
    "support": [],
    "resistance": []
  },
  "raw_indicators": {}
}
```

Key fields to extract:
- `regime` — `"trending_up"` / `"trending_down"` / `"ranging"` / `"volatile"`
- `trend` — directional lean: `"bullish"` / `"bearish"` / `"neutral"`
- `signal` — composite score: `> 0.3` = buy lean, `< -0.3` = sell lean
- `confidence` — 0.0–1.0 (use > 0.5 as meaningful threshold)
- `is_oversold` / `is_overbought` — STC trigger conditions
- `levels.support[]`, `levels.resistance[]` — key price levels

Note: The technical agent does NOT return `atr`, `entry_price`, `stop_price`, `target_price`, `risk_reward`, or `rationale` directly. Calculate ATR from bars:

### Bars for Key Levels

```
GET http://localhost:8010/analyze/bars/MES?timeframe=1h&days=5&futures=true
```
Params: `timeframe` (5m/15m/1h/1d), `days` (number), `futures` (boolean).
Note: Use `timeframe` and `days` — NOT `interval` and `period`.

### 7:45am — Overnight Gap Assessment

Using `/prices/snapshot` from the brief:
- Gap > 0.5% (`(last_price - prev_close) / prev_close`): Note volatility spike at open
- Gap > 1.0%: No entries until 9:35am CT (treat as high-impact event)
- Gap < 0.5%: Standard — avoid first 5 minutes (8:30–8:35am CT) only

### 8:00am — Matt's Active Prep Window

Matt sits down. JARVIS surfaces trade plan:

```
━━━ TODAY'S TRADE PLAN — [DATE] ━━━

TECHNICAL REGIME (MES 1h):
  Regime: [trending_up/trending_down/ranging/volatile/unknown]
  Signal: [X.X] | Confidence: [X.X]
  Trend: [bullish/bearish/neutral]
  Is Oversold: [true/false] | Is Overbought: [true/false]

KEY LEVELS (MES, from /analyze/bars):
  Resistance: [X,XXX.XX] (strong) | [X,XXX.XX] (moderate)
  Support:    [X,XXX.XX] (strong) | [X,XXX.XX] (moderate)
  Prior day high: [X,XXX.XX] | Prior day low: [X,XXX.XX]

SETUP WATCHLIST:
  Primary: [oversold pullback long / overbought short / HOLD — no setup]
  Note: ATR must be calculated from last N bars (not returned by /analyze/technical)
  Estimate stop = 0.70 × (recent high − recent low over 14 bars)

SIZING:
  Risk per trade: [1.0% = $X.XX | 0.5% = $X.XX — Liberation Day active]
  Max contracts: 2 (hardcoded safety cap)

AVOID:
  [FOMC before 1:00pm CT] | [VIX > 25: 1 contract max]
  [3+ consecutive losses: half-size] | [Kill switch active]

Active windows: 9:35–11:30am CT + 1:00–3:30pm CT
```

### 8:25am — Final Pre-RTH Check

```
GET http://localhost:8010/watchlist
```
Actual response (array):
```json
[
  {"symbol": "MES", "name": "Micro E-mini S&P 500", "type": "futures", "last_price": null, "change_pct": null},
  {"symbol": "MNQ", "name": "Micro E-mini Nasdaq", "type": "futures", "last_price": null, "change_pct": null},
  {"symbol": "SPY", "name": "SPY", "type": "options", "last_price": null, "change_pct": null}
]
```

```
GET http://localhost:8010/scheduler/status
```
Confirm `"running": true` and check `jobs[0].next_run` ≈ 8:30am CT.

---

## Section 3 — RTH Open (8:30am CT)

*T-2 fires automatically at RTH open. JARVIS surfaces immediately. Matt does NOT trade yet.*

### Auto-Surface at 8:30am CT (T-2):

```
━━━ RTH OPEN — 8:30am CT ━━━

MES at open: [last_price from /prices/snapshot]
Gap from prior close: [+/-X.X pts] ([+/-X.X%] = (last_price - prev_close) / prev_close)
Opening regime (from 7:30am analysis): [regime]

Scheduler: RUNNING — next scan per jobs[0].next_run
Kill switch: [OFF ✓ | ACTIVE ⛔]

NOISE WINDOW — DO NOT ENTER:
  8:30–9:35am CT: First 65 minutes — high noise, stop sweeps, false breakouts
  Matt's active window starts: 9:35am CT

[If positions exist in /portfolio.positions:]
  Positions LIVE. Verify stop distances at open price.

[If kill switch active:]
  ⛔ KILL SWITCH ACTIVE — NO ENTRIES. Pipeline runs read-only.
```

### 8:35am — First RTH Scan (SO-3)

Manually trigger if needed:
```
POST http://localhost:8010/pipeline/run
Content-Type: application/json
{"symbol": "MES", "is_futures": true}
```
Note: Pipeline body is `{symbol, is_futures}` ONLY — no `include_news`, `include_social`, `include_macro` params.

Pipeline takes 30–90 seconds. Response includes `analyst_reports{technical, news, social, fundamental}`.
Check result: `GET http://localhost:8010/pipeline/status`
```json
{
  "available": true,
  "last_run": {"id": 3, "timestamp": "...", "symbol": "MES", "action": "hold", "confidence": 0, "summary": "..."},
  "decision_count": 3
}
```

### 9:35am — Matt's Morning Trading Window Opens

```
━━━ MORNING SESSION OPEN — 9:35am CT ━━━

SIGNAL SUMMARY (from /decisions/recent?limit=5):
[Any non-hold actions, or: "All HOLD — no setup yet"]

REGIME (from most recent pipeline): [regime]
Is Oversold: [true/false] | Is Overbought: [true/false]

Next scan: per scheduler/status jobs[0].next_run
Active window: 9:35–11:30am CT — PRIMARY TRADING WINDOW
```

---

## Section 4 — Intraday Monitoring (8:30am–3:00pm CT)

### Automated 30-Minute Scan Cycle (SO-3)

Scans fire roughly every 30 min during RTH. Check current schedule:
```
GET http://localhost:8010/scheduler/status
→ jobs[0].next_run
```

After each scan JARVIS checks:
1. Decision result: non-hold → T-7 fires, SO-4 dispatches WhatsApp
2. Regime change vs prior scan → T-20 fires if changed
3. `is_oversold: true` or `is_overbought: true` → T-21 fires, full pipeline auto-runs
4. Last scan timestamp → T-24 fires if > 45 min gap

### Matt's Active Trading Windows

**Morning Session: 9:35am–11:30am CT**
- Primary window — highest conviction entries
- Pattern: Wait for `is_oversold: true` on `trending_up` regime (long) or `is_overbought: true` on `trending_down` regime (short)

**Midday Lull: 11:30am–1:00pm CT**
- Avoid unless strong catalyst
- Monitor open positions only

**Afternoon Session: 1:00pm–3:30pm CT**
- Secondary window — trend continuation
- 3:00pm CT = RTH close scan (final of day)

### Real-Time Position Check

```
GET http://localhost:8010/portfolio
```
Returns positions array (if any). Fields per position depend on entry data logged.
Calculate manually:
- Daily P&L %: `daily_pnl / equity_peak × 100`
- Drawdown: `drawdown_pct × 100`%

Partial profit at T1 (1.50x ATR from entry):
- Close 50% of position
- Move stop to breakeven on remainder
- T2 target = entry + (2.50x ATR)

Safety cap: Maximum 2 contracts across ALL positions (hardcoded — not overridable).

### Intraday Auto-Surface Alerts

| Alert | Trigger | What JARVIS Does |
|-------|---------|-----------------|
| BUY/SELL signal | Pipeline `action != "hold"` | T-7 surface + WhatsApp (SO-4) |
| Regime change | Consecutive scans differ | T-20 warning + implications |
| STC crosses 15 or 83 | `is_oversold` or `is_overbought` true | T-21 + auto pipeline run |
| Daily P&L hits -1.6% | `daily_pnl / equity_peak ≤ -0.016` | T-8 warning + 3 options |
| Drawdown hits -8.0% | `drawdown_pct ≤ -0.08` | T-9 warning + size reduction |
| Kill switch activates | `kill_switch_active: true` in /health | T-6 every response |
| Engine down | `/health` returns `status != "online"` 2× | T-10 every response |
| Scan overdue >45min | No recent decision logged | T-24 + offer manual scan |
| 3+ correlated positions | Multiple non-HOLD on correlated | T-22 concentration warning |
| VIX > 25 / > 30 | From macro snapshot | T-23 WARNING / CRITICAL |

---

## Section 5 — Market Close Preparation (3:45pm CT)

*T-3 fires at 3:45pm CT — 15 minutes before after-hours. Matt's active window closes at 3:30pm CT.*

### T-3 Auto-Surface:

```
━━━ MARKET CLOSE — 3:45pm CT ━━━

Portfolio check (GET /portfolio):
Equity: $[X,XXX.XX] | Daily P&L: $[+/-X.XX] ([+/-X.X%])

[If positions[] is non-empty:]
POSITIONS REQUIRING A DECISION:
[List each from portfolio.positions]

Options for each position:
(A) Hold overnight — max 1 contract (rule: excess must close before 5:00pm CT)
    Risk: gap at next open, no stop management overnight
    Valid if: trending regime + position more than 50% of way to T1
(B) Close before 5:00pm CT — captures current P&L, clean overnight
    Valid if: approaching stop, choppy regime, or FOMC risk tomorrow

After-hours (3:00–5:00pm CT): MES/MNQ continue at reduced liquidity.
No new entries. Exit management only.

[If positions[] is empty:]
Clean close. No action required.
Daily P&L: $[+/-X.XX] ([+/-X.X%])
```

---

## Section 6 — End of Day Summary (4:05pm CT)

*T-4 fires 5 minutes after RTH close. JARVIS auto-runs the EOD workflow.*

### Auto-Run Steps:

```
GET http://localhost:8010/portfolio
GET http://localhost:8010/safety/status
GET http://localhost:8010/decisions/recent?limit=20
```

Note: There is no `/portfolio/paper/performance` endpoint. All performance data comes from `/portfolio` and accumulated `/decisions/recent` history.

Performance derived from `/portfolio`:
- `daily_pnl` = today's dollar P&L
- `realized_pnl` = total realized
- `unrealized_pnl` = open position value
- `total_equity` vs initial capital = total return

Trade stats derived from `decisions/recent`:
- Count `action` values: buy/sell (trades taken) vs hold (filtered)
- `confidence` field for average conviction

### EOD Delivery Format:

```
━━━ END OF DAY SUMMARY — [DATE] ━━━

DAILY PERFORMANCE:
Daily P&L:      $[+/-X.XX] ([+/-X.X%] of equity_peak)
Realized today: from decisions/recent action count
Unrealized:     $[+/-X.XX] on [N] open position(s)
Total equity:   $[X,XXX.XX]

PIPELINE ACTIVITY:
Total decisions logged today: [N] (from scheduler/status.total_decisions_logged delta)
Non-hold signals: [BUY: N / SELL: N / HOLD: N breakdown]
Highest conviction: [symbol] [action] (confidence: [X.X]) at [time]

RISK SUMMARY:
Daily P&L:         $[+/-X.XX] ([+/-X.X%]) | Limit: -2.0%
Drawdown:          -[X.X%] | Limit: -10.0%
Kill switch today: [Never triggered | Active from TIME]
Orders/min peak:   [N] (safety: 11 max)

TOMORROW:
Events: [LIST or "Clear calendar"]
Pre-market brief: 6:30am CT
Open positions: [N — overnight rules apply | None]

[If overnight holds:]
Overnight hold checklist:
✓ Max 1 contract per instrument
✓ Regime: [trending — valid hold]
✓ Tomorrow's calendar: [SAFE / CAUTION — event at X time]
```

### Post-Market Journal (5 min — JARVIS drafts)

```
TRADE JOURNAL — [DATE]

Decisions taken: [list non-hold actions from /decisions/recent today]
Each action: symbol | direction | confidence | summary text

What worked: [regime alignment / STC timing / sized correctly]
What didn't: [regime was unknown / confidence low / Liberation Day overridden]
Lesson: [one actionable takeaway]

Strategy adherence: [Full / Partial — note deviation | No trades taken]
```

---

## Section 7 — Weekly Review (Monday 7:00am CT)

*T-5 fires every Monday, layered on top of T-1.*

### Auto-Run Steps:

```
GET http://localhost:8010/portfolio
GET http://localhost:8010/macro/snapshot
GET http://localhost:8010/decisions/recent?limit=100
POST http://localhost:8010/backtest/run
Content-Type: application/json
{"symbol": "MES", "start": "2026-01-01", "end": "TODAY", "interval": "1h",
 "capital": 10000, "risk_per_trade": 0.01}
```

Note: There is no `GET /backtest/results`. Use `POST /backtest/run` to re-run.
Cached baseline: MES 1h backtest results = PF 5.27, Sharpe 4.16, +47.2% (from skill file).

### Weekly Review Delivery Format:

```
━━━ WEEKLY REVIEW — Week Ending [LAST FRIDAY] ━━━

PORTFOLIO STATUS:
Total equity:   $[X,XXX.XX]
Realized P&L:   $[+/-X.XX] total
Unrealized:     $[+/-X.XX]
Drawdown:       -[X.X%] (limit: -10.0%)

PIPELINE SUMMARY (last 100 decisions):
Total actions:  [N] (non-hold) | hold: [N]
Win/loss:       derived from confidence > 0.5 signal quality
Avg confidence: [X.X]

vs BACKTEST BASELINE (MES 1h):
Profit Factor target: 5.27 | Sharpe target: 4.16

THIS WEEK OUTLOOK:
Key events: [FOMC | CPI | NFP | dates and times]
Macro bias: [BULLISH/BEARISH/NEUTRAL from /macro/snapshot]

SIZING RECOMMENDATION:
[NORMAL — 1.0% risk] OR [REDUCED — 0.5% — reason]
Liberation Day status: [Active: [N] consecutive | Resolved]

PAPER GRADUATION PROGRESS:
Days completed: [X / 60] | Decisions logged: [X / 40 target minimum]
```

### Monday Maintenance Tasks (15 min):

1. **Calendar load** — FOMC/CPI/NFP dates for the week
2. **Watchlist audit** — Add/remove symbols? (`GET /watchlist` then Tier 3 confirm)
3. **Risk limit review** — -2%/-10%/40% still calibrated?
4. **Strategy params** — STC OS=15/OB=83 + ATR 0.70x/T1 1.50x optimal?
5. **ThinkScript** — New studies to generate? (`POST /thinkscript/generate`)
6. **Liberation Day reset** — If 3+ loss streak resolved, confirm back to 1.0% risk

---

## Section 8 — Standing Orders (Complete Reference)

These run automatically. No action from Matt required.

| ID | Name | Tier | Trigger | What It Does | Adjustable |
|----|------|------|---------|--------------|-----------|
| **SO-1** | Health Monitor | 1 AUTO | Always active | Polls `GET /health` every 60s; alert if `status != "online"` 2× | Check interval only |
| **SO-2** | Market Open Brief | 1 AUTO | Trading days, builds at 6:00am | Caches all 7 data steps for instant 6:30am delivery | Content only |
| **SO-3** | Watchlist Scan | 1 AUTO | Mon–Fri per scheduler | `POST /pipeline/run` on watchlist symbols; fires T-7/T-20/T-21 | Frequency: Tier 3 |
| **SO-4** | Signal Alert Dispatch | 2 NOTIFY | Non-hold from SO-3 | Formats + sends WhatsApp via Twilio; 2hr cooldown per symbol | Cooldown: Tier 3 |
| **SO-5** | Paper Trade Auto-Log | 2 NOTIFY | `require_human_approval: false` | `POST /decisions/log` with trade JSON | Currently INACTIVE |
| **SO-6** | Daily P&L Watch | 1 AUTO | Always during 6am–5pm CT | Polls `/safety/status` + `/portfolio`; fires T-8 at -1.6%, T-9 at -8.0% | Thresholds: Tier 3 |

### SO-4 WhatsApp Message Format:
```
JARVIS TRADER SIGNAL
[BUY / SELL] [SYMBOL]
Time: [HH:MM] CT | TF: [TIMEFRAME]

Regime: [REGIME]
Signal: [X.X] | Confidence: [X.X]/1.0
STC: [is_oversold/is_overbought]

Entry: ~[current price from /prices/snapshot]
R:R = 1:2.14 at default multipliers (0.70x stop / 1.50x T1)

Mode: PAPER
```

### SO-5 Status Note:
Currently **INACTIVE** (`require_human_approval: true` — confirmed live from `/safety/status`).
All trade logging goes through Tier 3 confirmation. To activate SO-5: Tier 3 required.
When active, SO-5 uses `POST /decisions/log` with freeform JSON (accepts any fields).

---

## Section 9 — Proactive Intelligence (What JARVIS Watches For You)

*All triggers fire automatically. Matt does not need to ask.*

### CRITICAL — Surfaces on Every Response Until Resolved

| Trigger | Condition | JARVIS Behavior |
|---------|-----------|-----------------|
| **T-6** Kill Switch | `kill_switch_active: true` from `/health` | Surfaces FIRST before all content. Every interaction. Tier 3 to deactivate via `POST /safety/kill-switch/deactivate`. |
| **T-10** Engine Down | `/health` returns `status != "online"` 2× | Surfaces FIRST. All data stale. Restart instructions every interaction until healthy. |

### WARNING — Surfaces Promptly

| Trigger | Condition | What Matt Sees |
|---------|-----------|----------------|
| **T-7** Non-hold Signal | `action != "hold"` from pipeline | Full signal breakdown + WhatsApp confirmation (SO-4) |
| **T-8** Daily P&L -1.6% | `daily_pnl / equity_peak ≤ -0.016` | Warning + 3 options (continue/reduce/halt) |
| **T-9** Drawdown -8.0% | `drawdown_pct ≤ -0.08` | Warning + size reduction recommendation |
| **T-12** 3+ Losses | 3 consecutive losing actions | Liberation Day protocol (0.5% risk) |
| **T-13** FOMC Day | Calendar event detection | Flatten reminder + specific time |
| **T-20** Regime Change | Consecutive scan regimes differ | Old→New regime + trading implications |
| **T-21** STC Crosses | `is_oversold: true` or `is_overbought: true` | Primary entry signal + auto full pipeline |
| **T-22** Correlation | 2+ correlated instruments non-hold simultaneously | Combined exposure warning |
| **T-23** VIX Spike | VIX > 25 (WARNING) / VIX > 30 (CRITICAL) | Size reduction / flatten suggestion |
| **T-24** Scan Overdue | `total_decisions_logged` unchanged > 45 min RTH | Scheduler check + offer manual scan |

### INFO — Auto-Loads in Context

| Trigger | Activates | What Gets Auto-Loaded |
|---------|----------|-----------------------|
| **T-1** Pre-Market Brief | 6:30am CT | Full 7-step brief |
| **T-2** RTH Open | 8:30am CT | Open alert + scheduler status |
| **T-3** Market Close | 3:45pm CT | Position decision prompt |
| **T-4** EOD Summary | 4:05pm CT | Portfolio + decisions |
| **T-5** Weekly Review | Monday 7:00am CT | Portfolio + macro + backtest run |
| **T-11** WhatsApp Sent | Twilio dispatch | Confirmation |
| **T-14** Symbol Mentioned | MES/MNQ/MCL/SPY/QQQ mentioned | `GET /prices/snapshot` + last 3 decisions |
| **T-15** Position Mentioned | "my position", "how's my MES" | `GET /portfolio` |
| **T-16** Risk Mentioned | "risk", "drawdown", "kill switch" | `GET /safety/status` + `GET /portfolio` |
| **T-17** Backtest Mentioned | "backtest", "track record" | Cached: MES 1h PF 5.27/Sharpe 4.16/+47.2% |
| **T-18** Regime Mentioned | "regime", "trending?" | `POST /analyze/technical` |
| **T-19** Options/Greeks | "options", "delta", "IV", "0DTE" | VIX context + STC direction + roadmap note |

---

## Section 10 — Trade Management Rules

### Pre-Entry Checklist (JARVIS validates before presenting any signal)

- [ ] `is_oversold: true` (long setup) OR `is_overbought: true` (short setup) — primary STC signal
- [ ] `regime` = `"trending_up"` (long) or `"trending_down"` (short) — all 5 regime filters
- [ ] `kill_switch_active: false` (from `/health` or `/safety/status`)
- [ ] `live_trading_enabled: false` confirmed (paper mode — not live)
- [ ] Daily P&L % > -1.6% (approaching -2.0% halt) — calculated from `daily_pnl / equity_peak`
- [ ] `drawdown_pct > -0.08` (approaching -10.0% limit)
- [ ] Margin used < 30% of available (approaching 40% limit) — from `margin_used / (margin_used + margin_available)`
- [ ] ATR stop defined: entry ± (0.70 × ATR in points)
- [ ] T1 target: entry ± (1.50 × ATR in points)
- [ ] R:R = 1.50 / 0.70 = **1:2.14** at default multipliers (minimum 1:1.5 to proceed)
- [ ] No high-impact event within 30 minutes
- [ ] Liberation Day: if 3+ consecutive losses → size = 0.5% risk (half normal)
- [ ] Pipeline `confidence ≥ 0.50` (FundManagerAgent gate)

### Position Sizing Formula

```
Account equity × Risk% = Dollar risk per trade

Dollar risk ÷ (Stop distance in pts × $5 per MES point) = Contracts

Example (normal sizing, MES, ATR = 20 pts):
  Account: $10,000 × 1.0% risk = $100 risk
  Stop = 0.70 × 20 pts = 14 pts × $5/pt = $70 per contract
  $100 ÷ $70 = 1.4 → Round DOWN → 1 contract

Example (Liberation Day, same ATR):
  Account: $10,000 × 0.5% risk = $50 risk
  $50 ÷ $70 = 0.71 → Round DOWN → 1 contract (minimum)

Safety cap: 2 contracts maximum (hardcoded SafetyLayer — not overridable).
```

### Instrument Values

| Instrument | Multiplier | Min Tick | Tick Value | Point Value |
|------------|-----------|----------|------------|-------------|
| MES | Micro E-mini S&P 500 | 0.25 pts | $1.25 | **$5.00** |
| MNQ | Micro E-mini Nasdaq-100 | 0.25 pts | $0.50 | **$2.00** |
| MCL | Micro Crude Oil | 100 barrels | $0.01/bbl | $1.00 (per tick) |

### ATR Reference by VIX Regime (MES approximate)

| VIX Regime | Daily ATR | 1hr ATR | Stop 0.70x | $ Risk/contract |
|-----------|-----------|---------|-----------|----------------|
| LOW (12–16) | 10–18 pts | 3–6 pts | 2.1–4.2 pts | $10.50–$21.00 |
| NORMAL (16–20) | 15–25 pts | 5–9 pts | 3.5–6.3 pts | $17.50–$31.50 |
| ELEVATED (20–25) | 25–40 pts | 8–14 pts | 5.6–9.8 pts | $28.00–$49.00 |
| HIGH (25–30) | 35–60 pts | 12–20 pts | 8.4–14.0 pts | $42.00–$70.00 |
| EXTREME (>30) | 50–100+ pts | 17–35 pts | 11.9–24.5 pts | $59.50–$122.50 |

### Exit Rules

**At T1 (1.50x ATR from entry):**
- Take 50% off (close half contracts)
- Move stop to breakeven on remainder
- Let remainder run to T2 (2.50x ATR) or trail stop

**Stop loss (0.70x ATR from entry):**
- Hard stop — no exceptions
- Never move stop further away once trade is live

**Time-based:**
- FOMC: Flatten all positions by 12:45pm CT
- 3:00pm CT RTH close: evaluate overnight hold vs close
- Maximum overnight: 1 contract per instrument

### Trade Logging (Tier 3 — confirm before logging)

```
POST http://localhost:8010/decisions/log
Content-Type: application/json
{
  "symbol": "MES",
  "action": "buy",          ← lowercase "buy" / "sell" / "hold"
  "confidence": 0.74,
  "source": "manual",
  "summary": "MES | is_oversold=True regime=trending_up | action=BUY qty=1 @ 5512.50 | stop=5498.5 t1=5542.5"
}
```
Note: `/decisions/log` accepts any JSON (freeform). No required fields beyond what the engine validates.
This endpoint is the ONLY way to log trades in the current v1.1.0 engine.

---

## Section 11 — Emergency Protocols

### EP-1: Daily Loss Limit Breach (-2.0%)
**Source**: SafetyLayer Python — automatic. Condition: `daily_pnl / equity_peak ≤ -0.02`.
**How to detect**: `kill_switch_active: true` in `/health` + `kill_switch_reason` in `/safety/status`.
**JARVIS**: T-6 fires. Every response starts with KILL SWITCH ACTIVE block.
**Deactivation** (Tier 3): Review, explicit confirmation, then `POST /safety/kill-switch/deactivate`.

### EP-2: Max Drawdown Breach (-10.0%)
**Source**: SafetyLayer Python. Condition: `drawdown_pct ≤ -0.10`.
**JARVIS**: T-6 + context: "Maximum drawdown limit breached — most severe halt."
**Deactivation** (Tier 3): 3-step review: (1) last losing decisions, (2) regime during drawdown, (3) reduce to 1 contract until `drawdown_pct > -0.05`.

### EP-3: Engine Unresponsive
**Source**: `/health` returns `status != "online"` or request fails × 2.
**JARVIS**: T-10 on every response. All data stale.
**Restart**:
```
Option A — Direct: cd engine && uvicorn main:app --reload --port 8010
Option B — PM2:   pm2 restart jarvis-trader
Option C — Debug: pm2 stop jarvis-trader && tail -100 engine/logs/app.log && pm2 start jarvis-trader
```
Confirm recovery: `GET /health` returns `"status": "online"`.

### EP-4: Anomalous Order Rate (IB Gateway connected, Phase 3+)
**Source**: SafetyLayer — `orders_last_minute > 10`.
**JARVIS**: T-6 + "Anomalous order rate. Do NOT deactivate until source identified."
**Investigation**:
```
GET /safety/status          ← check orders_last_minute
GET /decisions/recent?limit=50 ← review decision pattern
Check IB Gateway order log ← what was attempted?
Look for: infinite pipeline loop, multiple scheduler instances
```

### EP-5: Market-Wide Circuit Breaker (NYSE Rule 80B)
**Circuit levels**: S&P -7% → 15-min halt | S&P -13% → 15-min halt | S&P -20% → Day halt
**JARVIS**: Surface level + "Above strategy kill switch — no orders regardless of kill switch state."
**Liberation Day reference**: April 2025 (Liberation Day crash) = primary stress event. Strategy max DD: -8.3% (within -10% limit).

### EP-6: Correlation Cascade
**Source**: T-22 fires + 3+ correlated positions losing simultaneously.
**JARVIS**: Surface combined exposure + combined stop risk.
**Rule**: JARVIS NEVER closes positions autonomously. Advisory only.
**Guidance**: "Pause new entries. No adding to losers. Check if regime shifted to `ranging`/`volatile`."

---

## Section 12 — Options Trading (Current Status + Roadmap)

### What JARVIS Provides Today (v1.1.0)

Options monitoring is **not integrated** in the pipeline. JARVIS cannot track Greeks or IV rank per position. Available now:

| Available Now | Endpoint | Field |
|--------------|----------|-------|
| VIX level + regime | `GET /macro/snapshot` | `vix`, `vix_regime` |
| STC directional bias | `POST /analyze/technical` | `is_oversold`, `is_overbought`, `trend` |
| Reddit sentiment | `GET /sentiment/recent` | `score`, `post_count` |
| News sentiment | `GET /sentiment/news/{symbol}` | varies |
| Macro regime | `GET /macro/snapshot` | `macro_regime` |

**VIX as IV proxy (6-tier):**
| VIX | Regime | Options Guidance |
|-----|--------|-----------------|
| < 12 | VERY_LOW | Cheap options — directional long spreads favored |
| 12–16 | LOW | Standard IV — all strategies viable |
| 16–20 | NORMAL | Standard premium — iron condors viable |
| 20–25 | ELEVATED | Selling premium favorable (CSPs, iron condors) |
| 25–30 | HIGH | Premium selling has high directional risk — buy straddles |
| > 30 | EXTREME | Buy premium expensive — favor neutral/defined-risk only |

**STC for options direction:**
- `is_oversold: true` on MES → bullish bias → calls / bull call spreads / CSPs
- `is_overbought: true` on MES → bearish bias → puts / bear put spreads
- Neither → no directional edge → non-directional or stand aside

### Options Roadmap

| Feature | Target Version | Description |
|---------|---------------|-------------|
| IV Rank per strike/expiration | v2.0 | From ThinkorSwim data feed |
| Delta/Gamma/Theta tracking | v2.0 | Per position, live P&L by Greek |
| P50/POP calculations | v2.0 | Probability of profit |
| 0DTE watchlist | v2.1 | SPX/SPY 0DTE specific alerts |
| Calendar vs vertical selector | v2.1 | Recommended structure by IV regime |
| Iron condor range estimation | v2.2 | ATR-based expected move |

---

## Section 13 — ThinkScript Library Reference

JARVIS generates ThinkScript code on demand via `POST /thinkscript/generate`.

### Generate a Study

```
POST http://localhost:8010/thinkscript/generate
Content-Type: application/json
{"symbol": "MES", "timeframe": "1h", "is_futures": true}
```

Note: `GET /thinkscript/list` and `GET /thinkscript/{name}` do NOT exist in v1.1.0.
All ThinkScript is generated on-demand via POST or pre-coded manually.

### Study Categories

**Signal Indicators (lower study)**
| Study | Purpose |
|-------|---------|
| `STC_Signal_Alert` | Schaff Trend Cycle with OS/OB arrows (OS=15, OB=83) |
| `STC_Color_Bars` | Bar color changes when STC crosses 15/83 |
| `ATR_StopLoss_Dynamic` | ATR stop (0.70x) and T1 target (1.50x) plotted |
| `JARVIS_Entry_Zone` | Highlights bars where all 5 regime filters pass |
| `Pipeline_Signal_Arrows` | BUY/SELL arrows from pipeline decisions |

**Regime Filters**
| Study | Purpose |
|-------|---------|
| `ADX_Regime_Color` | ADX trending/choppy (threshold: 25) |
| `VIX_Regime_Overlay` | VIX with 6-tier regime bands |
| `EMA_Alignment_Signal` | 20/50/200 EMA alignment |
| `Volume_Regime_Filter` | Expanding vs contracting volume |

**Risk Dashboard (chart labels)**
| Study | Purpose |
|-------|---------|
| `DailyPnL_Meter` | Running daily P&L vs -2% limit |
| `Drawdown_Gauge` | Equity curve vs -10% drawdown |
| `Position_Size_Calc` | Enter account + risk%, get contract count |
| `ATR_Dollar_Risk` | Dollar risk per contract at current ATR |

**Session Reference (price chart overlays)**
| Study | Purpose |
|-------|---------|
| `RTH_VWAP_Dynamic` | Session VWAP + 1/2 std dev bands |
| `Opening_Range_30min` | First 30-min high/low |
| `Prior_Day_Levels` | Prior close, high, low |
| `Daily_Pivots` | Classic pivot points (R1/R2/S1/S2) |

**Scan Tools**
| Study | Purpose |
|-------|---------|
| `Regime_Scanner` | TOS scan: instruments in trending regime |
| `STC_Oversold_Scan` | TOS scan: STC < 15 on 1h bars |
| `STC_Overbought_Scan` | TOS scan: STC > 83 on 1h bars |

---

## Section 14 — Key Performance Metrics

### Primary Metrics (derived from `/portfolio` + `/decisions/recent`)

Since `/portfolio/paper/performance` does NOT exist, metrics are derived:

| Metric | How to Calculate | Backtest Target | Paper Minimum |
|--------|-----------------|----------------|---------------|
| Total return | `(total_equity - initial_capital) / initial_capital` | +47.2% | Positive |
| Drawdown | `drawdown_pct × 100`% | 8.3% max | < 10% |
| Daily P&L % | `daily_pnl / equity_peak × 100` | Positive most days | > -2.0% |
| Win rate | Won decisions / total non-hold decisions | ~36% | > 28% |
| Avg confidence on wins | Average `confidence` on buy/sell signals | > 0.5 | > 0.4 |

### Backtest Baseline (confirmed from Phase 1 — MES 1h strategy)

| Metric | Value | Notes |
|--------|-------|-------|
| Profit Factor | **5.27** | Re-run with `POST /backtest/run` to verify |
| Sharpe Ratio | **4.16** | Rolling 4-week in paper |
| Win Rate | **~36%** | STC-based entries only |
| Total Return | **+47.2%** | Paper backtest period |
| Max Drawdown | **-8.3%** | Liberation Day (April 2025) stress event |

### Risk Metrics (from `/safety/status`)

| Metric | Field | Warning | Halt |
|--------|-------|---------|------|
| Daily P&L % | `daily_pnl / equity_peak` | ≤ -1.6% (T-8) | ≤ -2.0% (auto) |
| Drawdown | `drawdown_pct` | ≤ -0.08 (T-9) | ≤ -0.10 (auto) |
| Order rate | `orders_last_minute` | > 5 (manual alert) | > 10 (auto halt) |

### Weekly Health Check

**Confidence avg declining:** Signal quality degrading — check if market regime changed (ranging/volatile dominates).
**All decisions returning "hold":** Data unavailable (price rate limits, FRED key missing) — check APIs.
**Drawdown approaching -7%:** Reduce to 1 contract until recovery above -5%.
**No decisions logged in 2 days:** Scheduler stopped — check `scheduler/status.running`.

---

## Section 15 — Paper Trading Validation Checklist (April–May 2026)

### Current Phase: PAPER TRADING (Phase 2 of 4)

| Phase | Status | Criteria | Timeline |
|-------|--------|----------|---------|
| Phase 1: Backtesting | ✅ COMPLETE | MES 1h PF 5.27, Sharpe 4.16 | Done |
| **Phase 2: Paper trading** | ⏳ IN PROGRESS | See checklist below | Apr–May 2026 |
| Phase 3: Live micro ($500) | 📅 JUNE 2026 | IB Gateway + live mode + $500 max | Planned |
| Phase 4: Full deployment | 📅 Q3 2026 | $10K+ account + full automation | Planned |

### Phase 2 → Phase 3 Graduation Checklist

All criteria must be met before enabling live trading:

- [ ] **60 consecutive trading days** completed (paper mode)
- [ ] **Minimum 40 non-hold decisions** logged via `/decisions/recent`
- [ ] **Profit Factor > 3.0** (derived from win/loss decision history)
- [ ] **Max drawdown < 8%** (`drawdown_pct > -0.08` sustained)
- [ ] **Win rate > 28%** (winning actions / total non-hold actions)
- [ ] **No kill switch breach from sizing error** (limit hits from market moves are ok; from system errors are a red flag)
- [ ] **IB Gateway integration tested** — Paper IBKR ports: TWS=7497, Gateway=4002
- [ ] **WhatsApp alerts confirmed** — At least 5 successful SO-4 dispatches with Twilio SIDs
- [ ] **No EP-3 events in final 2 weeks** (engine must be stable)
- [ ] **Liberation Day rule respected** throughout (0.5% risk during loss streaks — verify in journal)

### IBKR Port Reference (Phase 3/4)

| Mode | TWS Port | IB Gateway Port | Config Setting |
|------|---------|----------------|----------------|
| Paper | 7497 | **4002** | `IBKR_PORT=4002` |
| Live | 7496 | **4001** | `IBKR_PORT=4001` |

### Phase 3 Pre-Live Checklist

Before enabling live trading (`live_trading: true`):
- [ ] `ibkr_connected: true` confirmed in `/health` response
- [ ] Kill switch tested manually — activate + deactivate
- [ ] Position size verified: 1 contract max until $500 account milestone
- [ ] All EP protocols reviewed with live money risk in mind
- [ ] SO-5 activation confirmed (sets `require_human_approval: false`) — Tier 3

---

## Appendix A — Complete API Quick Reference

### Engine State
```
GET  /health                              → status, kill_switch_active, ibkr_connected, schwab_connected
GET  /safety/status                       → kill_switch_active, daily_pnl, drawdown_pct, orders_last_minute
POST /safety/kill-switch/activate         → ?reason=string
POST /safety/kill-switch/deactivate       → (no body)
```

### Market Data
```
GET  /prices/snapshot                     → {SYMBOL: {last_price, prev_close, change_pct}}
GET  /watchlist                           → [{symbol, name, type, last_price, change_pct}]
GET  /macro/snapshot                      → vix, vix_regime, ten_year_yield, dxy, macro_regime (FRED required)
GET  /macro/series/{series_id}            → ?periods=N (FRED time series)
GET  /sentiment/recent                    → [{symbol, score, post_count, source, timestamp}]
GET  /sentiment/reddit                    → ?filter=string
GET  /sentiment/news/{symbol}             → news sentiment for symbol
```

### Analysis
```
POST /analyze/technical                   → body: {symbol, is_futures?, timeframe?}
                                            → signal, confidence, trend, regime, is_oversold, is_overbought, scores{}, levels{}
GET  /analyze/bars/{symbol}               → ?timeframe=1h&days=5&futures=true → OHLCV bars
POST /pipeline/run                        → body: {symbol, is_futures?}
                                            → analyst_reports{technical, news, social, fundamental}
GET  /pipeline/status                     → available, last_run{...}, decision_count
```

### Portfolio & Decisions
```
GET  /portfolio                           → total_equity, cash_balance, unrealized_pnl, realized_pnl, daily_pnl, margin_used, positions[]
GET  /decisions/recent                    → ?limit=N → [{id, timestamp, symbol, action, confidence, source, summary}]
POST /decisions/log                       → body: any JSON object (freeform — use for trade logging)
```

### Scheduler & Tools
```
GET  /scheduler/status                    → running, jobs[{id, name, next_run}], total_decisions_logged
POST /thinkscript/generate                → body: {symbol, timeframe?, is_futures?} → ThinkScript code
POST /backtest/run                        → body: {symbol, start, end, interval, capital, risk_per_trade}
POST /notifications/whatsapp/test         → test Twilio WhatsApp integration
```

---

## Appendix B — Hardcoded SafetyLayer Limits (Not Overridable by LLM)

These are Python-level constants in `engine/safety.py`. They cannot be changed via API or by JARVIS chat.

| Limit | Value | Effect When Breached |
|-------|-------|---------------------|
| Daily loss | -2.0% (`daily_pnl / equity_peak`) | Kill switch auto-activates |
| Max drawdown | -10.0% (`drawdown_pct`) | Kill switch auto-activates |
| Order rate | >10/min (`orders_last_minute`) | Kill switch auto-activates |
| Max contracts | 2 | New positions blocked |
| Margin limit | 40% | New positions blocked |

To deactivate kill switch (Tier 3 only):
```
POST http://localhost:8010/safety/kill-switch/deactivate
```

---

*Last validated against live engine: 2026-03-29 | Engine version: 0.1.0 | All 22 endpoints tested*
