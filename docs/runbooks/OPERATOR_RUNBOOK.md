# JARVIS Operator Runbook

**Owner:** Matt (single operator) · **Mode:** PAPER · **Last updated:** 2026-09-25

This is the document you read when you want to *use* JARVIS, not develop it.
It answers four questions:

1. **What is this system and how does it decide anything?**
2. **How do I read the dashboard?**
3. **How do I check whether a signal is trustworthy?**
4. **What do I do when something breaks?**

---

## 1. The system in one page

### 1.1 What JARVIS trades

| Asset class | Symbols | Status |
|---|---|---|
| Futures | **MES** | ✅ Trading (paper) — gate-v2 PASS, WFE 0.983 |
| | MGC | ⛔ Blocked — `DO_NOT_TRADE_SYMBOLS` |
| | MCL, MNQ, M2K | ⛔ Blocked — `DO_NOT_TRADE_SYMBOLS` |
| Options/equities | SPY, QQQ, AAPL, TSLA | ✅ Trading (paper) — accepted validation gap (2026-08-03) |

**MES is the only futures instrument authorised for paper trading.** It sits in
`paper_config.py enabled=True` with a gate-v2 PASS on file. Everything else in
the futures list is blocked by `DO_NOT_TRADE_SYMBOLS` — that list is enforced in
code, not by convention.

### 1.2 The layers

```
                    ┌─────────────────────────────────────┐
  DATA              │  MarketDataManager (waterfall)       │
                    │  Tier 0  thinkorswim RTD  ← live     │
                    │  Tier 1  IBKR                        │
                    │  Tier 2  Schwab                      │
                    │  Tier 3  Polygon                     │
                    │  Tier 4  CSV cache                   │
                    │  Tier 5  structured None (never 0)   │
                    └─────────────────────────────────────┘
                                     │
                    ┌─────────────────────────────────────┐
  INDICATORS        │  Indicator engine (derived)          │
                    │  ATR(14) · Keltner(20,3.5)           │
                    │  5/15/30-min S/R · day-range %ATR    │
                    └─────────────────────────────────────┘
                                     │
                    ┌─────────────────────────────────────┐
  DECISION          │  5-stage LLM pipeline                │
                    │  analysts → debate → trader →        │
                    │  risk manager → fund manager         │
                    └─────────────────────────────────────┘
                                     │
                    ┌─────────────────────────────────────┐
  SAFETY            │  SafetyLayer (pure Python, no LLM)   │
                    │  kill switch · daily loss halt ·     │
                    │  drawdown halt · symbol gates        │
                    └─────────────────────────────────────┘
                                     │
                    ┌─────────────────────────────────────┐
  EXECUTION         │  OrderRouter → IBKR paper (4002)     │
                    └─────────────────────────────────────┘
```

**The critical property:** the SafetyLayer is *pure Python logic*. No LLM
touches a risk decision. An agent can propose a trade; it cannot approve one
past the kill switch.

### 1.3 The waterfall rule (why a number is never zero)

Every price value carries its source. If IBKR is down, the read falls through
to Polygon, then the CSV cache, then returns `None` — **never a silent `0.0`**.
A zero on this system means a real zero, not "we don't know."

When a value is `null` in the dashboard, that is the system being honest, not
broken.

---

## 2. Reading the dashboard

Route: `http://127.0.0.1:3010/mission-control` (local, Basic Auth on).

### 2.1 Panel-by-panel

| Panel | What it tells you | What to do with it |
|---|---|---|
| **Risk & Safety** | Kill switch, daily P&L, drawdown, paper/live mode | If kill switch is ON, nothing trades. That is the system working. |
| **Drawdown Projection** | How many *average losing trades* until the -20% halt | ≤3 = reduce size or pause. This is your runway gauge. |
| **Trading Status Reconciliation** | paper_config × DO_NOT_TRADE × gate-v2, fused per symbol | Any disagreement shown here is a real config drift. Investigate before trading. |
| **Runtime Snapshot** | Read-only operator artifact — works even when the engine is down | Your fallback truth source. |
| **Market Brief Machine Score** | Scenario probabilities (continuation / rotation / failure) | **Check the age.** If stale, do not use for intraday framing. |
| **SPX Intraday Decision** | Intraday read with probability map | Analysis only — never routes orders. |
| **Paper Trade Audit** | Realized P&L, trade count, MES gate verdict | Your scoreboard. |
| **Gateway Watchdog** | Port 4002, engine connection, data freshness, mode | ALL GREEN = safe to trade. DEGRADED = find out why first. |
| **Trade Execution** | Paper order entry (MES/SPY/QQQ) | The only panel that *does* something. Kill-switch gated. |
| **Positions & Performance** | Cumulative P&L, win rate, profit factor | Strategy health at a glance. |
| **Signals & Pipeline** | Latest per-symbol signal + conviction + age | **Check the age column.** 2-day-old signals are not tradeable. |
| **Validation & Gates** | MES readiness (trade count, loss streak, validation gates) | Tells you whether MES has *earned* more size. |
| **Gate-v2 Verdicts** | Per-symbol PASS/FAIL with PF | The authorisation record. |
| **Engine & Data** | Status, uptime, IB exec/data legs, TV MCP | Uptime resets often = something is crash-looping. |
| **TOS Live Quotes** | SPY/QQQ/VIX with source badge | Source badge tells you *which tier* answered. |
| **TOS Indicators** | ATR, Keltner, S/R, day range — labelled `derived` | Your TOS-chart analytics, computed in-process. |
| **Trade Recommendations** | Newest pipeline recommendation | Read with the signal age in mind. |
| **Options Chain** | Near-the-money strikes, last/bid/ask/IV | Read-only options surface. |

### 2.2 Source badges — the honesty contract

| Badge | Meaning |
|---|---|
| `live` | Real-time tier, fresh within its staleness window |
| `static` | Cached/end-of-day — **not** tradeable as a real-time read |
| `derived` | Computed in-process from a live feed (e.g. ATR from RTD prices) — not a vendor study value |
| `TOS` / `IBKR` / `POLY` / `CACHE` | Which waterfall tier actually served the number |

If a badge says `CACHE`, you are looking at history.

---

## 3. How a signal is produced (and how to audit one)

### 3.1 The five stages

| Stage | Agent | Output |
|---|---|---|
| 1 | Analysts (technical, fundamental, news, sentiment) | Independent reports |
| 2 | Debate | Bull/bear case with dissents preserved |
| 3 | Trader | Proposed direction + size + levels |
| 4 | Risk manager | Position sizing, stop, invalidation |
| 5 | Fund manager | Final action: LONG / SHORT / HOLD |

**Run one manually:**
```
curl -X POST http://127.0.0.1:8010/pipeline/run/background \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"symbol":"MES","is_futures":true}'
```

**Check what ran:**
```
curl -H "X-API-Key: $API_KEY" http://127.0.0.1:8010/pipeline/status
```

### 3.2 Auditing a signal — the four questions

Before acting on any signal, answer these:

1. **How old is it?** Signals are stamped. A signal from two days ago reflects
   two-day-old market structure. Refresh before use.
2. **What gate-v2 verdict backs the symbol?** PASS = the strategy earned
   authorisation. FAIL/absent = it did not.
3. **What is the conviction?** 0.00 is HOLD — no edge claimed. 0.80 is a real
   claim.
4. **Is the market data fresh?** `market_data_fresh: true` in `/health`.

### 3.3 The indicator calculations

These are computed in `engine/data/tos_indicator_engine.py`:

**ATR(14)** — Average True Range over 14 one-minute bars.
```
TR = max(high − low, |high − prev_close|, |low − prev_close|)
ATR = mean(TR over last 14 bars)
```
*Why it matters:* your TOS chart's ±1 ATR bands and the day-range-as-%-ATR
compression gauge both derive from this one number.

**Keltner Channels (20, 3.5)** — volatility envelope around an EMA.
```
mid   = EMA(close, 20)
band  = ATR(14) × 3.5
upper = mid + band
lower = mid − band
```
*Why it matters:* price above `upper` is an expansion/breakout condition; price
inside the band is mean-reverting territory.

**Multi-timeframe S/R** — rolling max/min over 5 / 15 / 30 one-minute bars.
Same concept as your TOS 5min/15min/30min tops and bottoms.

**Day-range gauge** — `(day_high − day_low) / ATR × 100`.
Your TOS chart shows this as "Day Range ($38) is 49% of ATR ($77)". Under ~50%
= compressed (breakout setup); over ~80% = expanded (late to chase).

**⚠️ Provenance limit:** TOS's RTD server only answers native quote topics
(`LAST`/`BID`/`ASK`/`CLOSE`). ThinkScript study outputs — `ATRTrailingStopLE`,
`KeltnerChannels`, `AA_CoreyTscorev2` (your TPO Score) — are **not queryable by
name**. Verified empirically: 11 candidate study topics for `/ES:XCME` and `SPY`
all returned `None`. Everything in the TOS Indicators card is therefore
**derived**, and is labelled `derived` in both the API payload and the UI.

To get your *actual* TPO Score into the dashboard, add it as a **custom quote
column** in a TOS watchlist; TOS then exposes it as an RTD column topic.

### 3.4 Where the strategy parameters live

| What | File | Change authority |
|---|---|---|
| STC canonical params | `engine/backtest/signals.py` | Tier 3 approval |
| Risk limits (kill switch, drawdown, daily loss) | `engine/config.py` + runtime `engine/.env` | Tier 3 approval |
| Per-symbol paper enablement | `engine/paper_config.py` | Tier 3 approval |
| DO_NOT_TRADE list | `engine/config.py` | Tier 3 approval |
| Gate-v2 verdicts | `engine/data/gate_v2_verdicts/*.json` | Produced by backtest, not hand-edited |

**Rule:** anything in the left column that touches risk, routing, or the
kill-switch needs a `[safety-review]` PR before it changes.

---

## 4. Daily routine

### Pre-market (08:00–08:25 CT)
Two cron jobs already fire: `jarvis-premarket-readiness` (08:00) and
`jarvis-premarket-t5-gate` (08:25). T-5 is silent when everything passes and
prints **only the failing checks** when something died.

Your read:
1. Mission Control → Gateway Watchdog → **ALL GREEN?**
2. Drawdown Projection → runway acceptable?
3. Trading Status Reconciliation → **0 disagreements?**
4. Market Brief → check its age before using it.

### During session
- TOS Live Quotes for the live tape
- TOS Indicators for ATR/Keltner/S-R context
- Signals & Pipeline for fresh decisions
- Trade Execution for paper orders

### After close (16:30 CT)
`market-brief-daily-score` fires at 16:30 — it refreshes base rates and scores
any pending brief whose outcome now exists.

---

## 5. Troubleshooting

### "Gateway Watchdog shows DEGRADED"
1. Check port 4002: `netstat -ano | grep :4002 | grep LISTEN`
2. If no listener → the IB Gateway logged out. Restart it:
   `C:\Users\mattm\scripts\start-ibc-paper.bat`
3. **Approve the 2FA push on your phone.** IBC exits if it times out.
4. From the repository root, run the credential-free recovery keeper:
   `& ".\scripts\gateway-keeper-paper.bat"`
5. Do not accept port-open or HTTP 200 alone. Success requires the keeper to
   print PASS for `ibgateway_alive`, `execution_connected_verified`,
   `ib_execution_stale`, `ibkr_data_connected`, and `live_trading` (which must
   remain `False`). The helper reads the API key from the gitignored
   `engine/.env` and never prints it.

### "TOS Live Quotes is empty"
1. Is TOS running? `tasklist | grep thinkorswim`
2. Is the RTD port up? `netstat -ano | grep :12001 | grep LISTEN`
3. Check `/health` → `tos_rtd_connected`. If `false`, the adapter never
   connected — check `tos_rtd_details.last_error`.

### "TOS Indicators shows ATR warming"
Normal after an engine restart. ATR needs 14 one-minute bar closes, Keltner
needs 20 — roughly 20 minutes of market data. It is not an error.

### "Signals are days old"
The pipeline has not run. Trigger it manually (§3.1). If it fails, check
`engine/logs/engine-error.log` for the LLM provider chain — a 429/402 means
credits, not code.

### "Kill switch is active"
**Do not reset it manually.** The kill switch is a safety mechanism; resetting
it without understanding the trigger defeats its purpose. Investigate the
drawdown source first. Reset requires Tier 3 approval.

### "PM2 commands hang"
Known issue — the PM2 CLI wedges on this host while the daemon keeps working.
Services still restart on crash. To manage them:
```
taskkill /F /PID $(cat C:/Users/mattm/.pm2/pm2.pid)
pm2 resurrect
```

### "Dashboard won't load"
Auth is enforced when `DASHBOARD_AUTH_USER` + `DASHBOARD_AUTH_PASS` are set in
`dashboard/.env.local`. Credentials are there; remove both lines for an
open localhost dashboard.

---

## 6. Safety rules — non-negotiable

1. **`LIVE_TRADING_ENABLED = False`.** Paper until explicitly changed via a
   `[safety-review]` PR.
2. **MES is the only authorised futures instrument.** MCL/MNQ/MGC/M2K are
   blocked in code.
3. **The SafetyLayer is pure Python.** Never route a risk decision through an
   LLM.
4. **The kill switch is not a bug.** If it fires, the system is working.
5. **Never edit `engine/.env` or `dashboard/.env.local` concurrently** — they
   are single-writer shared files.
6. **Independently verify any claim of "verified."** The watchdog at
   `engine/scripts/independent_position_watchdog.py` exists precisely because
   engine-internal monitoring can lie when the engine is wedged.

---

## 7. Quick reference

| Task | Command |
|---|---|
| Engine health | `curl -H "X-API-Key: $API_KEY" localhost:8010/health` |
| Live quotes | `curl -H "X-API-Key: $API_KEY" 'localhost:8010/prices/snapshot?symbols=SPY,QQQ,VIX'` |
| Indicators | `curl -H "X-API-Key: $API_KEY" 'localhost:8010/tos/indicators?symbols=SPY'` |
| Run pipeline | `curl -X POST .../pipeline/run/background -d '{"symbol":"MES","is_futures":true}'` |
| Position watchdog | `engine/.venv/Scripts/python.exe engine/scripts/independent_position_watchdog.py --verbose` |
| Market scan | `curl -X POST .../pipeline/scheduler/manual-scan` |
| Restart gateway | `C:\Users\mattm\scripts\start-ibc-paper.bat`, approve 2FA, then `& ".\scripts\gateway-keeper-paper.bat"` from the repo root |
| Dashboard (local) | `http://127.0.0.1:3010/mission-control` |

**Ports:** 8010 engine · 3010 dashboard · 4002 IB paper · 4001 IB live
(never engine) · 12001 TOS RTD
