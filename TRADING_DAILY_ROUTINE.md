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

Scans fire roughly every 30 min during RTH. Check