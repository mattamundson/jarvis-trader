# HERMES Autonomous Monitoring System
> Your AI trading assistant runs 24/7 while you sleep or focus on other work.

> **⚠️ Delivery-path status (2026-07-21):** The Telegram/HERMES gateway was
> **stopped and disabled on 2026-07-20** after the shared-Gemini-key spend-cap
> incident (Hermes and jarvis-trader were using the same Google API key/project;
> 2 of 3 live surfaces were stopped). Until a dedicated key is provisioned and
> the gateway is restarted, the Telegram delivery described below is **not
> active** — the jobs may run but alerts will not reach your phone. Restart of
> the Hermes gateway is a coordinated procedure (`hermes-safe-restart.sh`), never
> a raw restart from a diagnostic flow.

## Overview

Three autonomous jobs monitor your trading system, run analysis, and alert you only when critical:

| Job | Schedule | Purpose | Alert Level |
|-----|----------|---------|-------------|
| **Morning Briefing** | 6:00 AM CT daily | Pre-market setup, positions, key levels | ALWAYS (formatted briefing) |
| **Hourly Check** | Every 60 min (RTH only) | P&L, positions, kill switch, signals | CRITICAL ONLY |
| **EOD Analysis** | 4:00 PM CT daily | Daily summary + tomorrow's priorities | ALWAYS |

---

## How It Works

### 1. Morning Briefing (6:00 AM CT)
**Job ID:** `7f467164e600`

Runs automatically every morning to prepare you for the trading day:

**What it checks:**
- Engine health (all systems operational?)
- Current paper positions (qty, entry, P&L impact)
- Daily P&L vs circuit breaker limits
- Market session status (pre-market, RTH, post-market)
- Recent signals from scanner
- High-impact economic events scheduled today
- Hidden Pivots key levels (ES, NQ, CL, GC)

**What you receive:**
```
JARVIS MORNING BRIEFING — [DATE] CT
Engine: healthy
P&L: +$180 | Drawdown: -0.0%
Positions: 3 open | Impact: SHORT 1 MES, LONG 2 MCL
Events: 1 high-impact at 1:00 PM CT (FOMC)
Bias: Bearish — watching ES 7,100 support
```

**Control:**
```
# To pause morning briefings
cronjob(action='pause', job_id='7f467164e600')

# To resume
cronjob(action='resume', job_id='7f467164e600')
```

---

### 2. Hourly Status Check (Every 60 min)
**Job ID:** `a1600f8586f1`

Runs silently throughout the trading day. **Only alerts you if something is wrong.**

**What it monitors:**
- Kill switch status (critical)
- Daily P&L approaching -$200 (soft stop)
- Drawdown > -5% (yellow flag)
- Connectivity issues (IB Gateway, engine)
- New scanner signals (high-momentum setups)

**Silent (all clear):**
```
12:00 CT | RTH Status: GREEN ✓
```

**Alert (something needs attention):**
```
13:45 CT | RTH Status: YELLOW
Daily loss: -$185 | Approaching soft stop
Position: SHORT 1 ES | Current P&L: -$95
→ Consider tightening stops or reducing exposure
```

**Critical alert (kill switch active):**
```
14:30 CT | RTH Status: RED 🚨
KILL SWITCH ACTIVE — Trading halted for 24 hours
Reason: Daily loss exceeded -8% (-$812.40)
Action: Review positions, wait for manual reset
```

**Control:**
```
# To pause hourly checks (e.g., during manual trading)
cronjob(action='pause', job_id='a1600f8586f1')

# Resume checks
cronjob(action='resume', job_id='a1600f8586f1')
```

---

### 3. End-of-Day Analysis (4:00 PM CT)
**Job ID:** `52f5286b9103`

Summarizes the day and automatically identifies your top 3 priorities for tomorrow.

**What it analyzes:**
- Daily P&L, win rate, largest win/loss
- Closed trades (count, avg winner, avg loser)
- Best trade (clearest edge) vs worst trade (biggest error)
- Circuit breaker violations (if any)
- Scanner signal accuracy (which signals fired well?)
- Tomorrow's market events and key zones

**What you receive:**
```
EOD SUMMARY — 2026-04-22
P&L: +$180 | Win Rate: 67% | Max Drawdown: -2.1%
Trades: 3 closed | Best: MCL +$95 | Worst: MES -$50
Status: GREEN — all limits intact

PRIORITIES FOR TOMORROW:
1. FOMC at 1:00 PM CT — volatility spike expected, tighten stops
2. ES key support 7,100 — watch for morning range breakout
3. MCL structure: higher lows forming — bias remains long
```

**Control:**
```
# Pause EOD analysis
cronjob(action='pause', job_id='52f5286b9103')

# Resume
cronjob(action='resume', job_id='52f5286b9103')
```

---

## Telegram Notifications

All three jobs deliver directly to your Telegram DM with HERMES. No web dashboard needed — all analysis comes to your phone in plain text.

**Message Format:**
- Morning briefing: Formatted, always sent
- Hourly check: One line if GREEN, full alert if YELLOW/RED
- EOD analysis: Formatted summary + 3 priorities

**To Stop All Notifications:**
```
cronjob(action='pause', job_id='7f467164e600')  # morning
cronjob(action='pause', job_id='a1600f8586f1')  # hourly
cronjob(action='pause', job_id='52f5286b9103')  # eod
```

**To Resume All:**
```
cronjob(action='resume', job_id='7f467164e600')
cronjob(action='resume', job_id='a1600f8586f1')
cronjob(action='resume', job_id='52f5286b9103')
```

---

## What "Autonomous" Means

You don't micromanage. HERMES:
- ✓ Monitors your positions and P&L continuously
- ✓ Runs analysis on a fixed schedule
- ✓ Alerts you only on critical events (kill switch, large losses)
- ✓ Provides structured briefings (morning, EOD) so you stay in context
- ✓ Never makes trades or changes positions without human approval
- ✓ Never wakes you for green status (all clear)

---

## Kill Switch Protection

The kill-switch **logic** is hardcoded Python (never LLM-driven). Its **thresholds** are config-sourced, not literals — from `engine/config.py` with `engine/.env` as the live source of truth. **Current live limits (verified 2026-07-21 against `engine/.env`): `-8% daily loss` (`MAX_DAILY_LOSS_PCT=0.08`, or a `$1,000` flat `MAX_DAILY_LOSS_USD` cap) or `-20% drawdown` from peak (`MAX_DRAWDOWN_PCT=0.20`).** It's a safety mechanism, not a trading signal.

> Note: `engine/config.py` still carries `MAX_DAILY_LOSS_PCT=0.06` / `MAX_DAILY_LOSS_USD=100` as code defaults (its docstring says it was "reconciled to .env" on 2026-06-25). `.env` has since drifted to `0.08` / `1000`; `.env` wins at runtime. Reconciling the config defaults + docstrings to the live `.env` values is a `[safety-review]` change and has not been made here.

**If kill switch fires:**
1. All trading halts automatically
2. You receive RED alert on Telegram with reason
3. Wait 24 hours or manually reset (requires reviewing the loss)
4. No trading resumes until you or HERMES resets it

---

## Next Steps: Integration Points

After autonomous monitoring is live, we'll build:

| Priority | Task | Impact |
|----------|------|--------|
| 1 | Trade decision logging automation | Feedback loop for edge refinement |
| 2 | Economic calendar API integration | Precise event timing + impact |
| 3 | Scanner rule integration | Pre-market alerts on high-probability setups |
| 4 | Options flow + gamma exposure | Intraday flow refinement |
| 5 | Telegram → Engine API bridge | Direct execution from Telegram (approval required) |

---

## File Locations

- **Job definitions:** `~/.hermes/cron/` (auto-managed)
- **Job logs:** `~/.hermes/cron/output/` (stored per job_id)
- **Engine health:** `http://localhost:8010/health`
- **Paper positions:** `http://localhost:8010/api/portfolio`
- **Decisions log:** `http://localhost:8010/api/decisions/log`

---

## Troubleshooting

**Job not running?**
```
# Check if it's scheduled
cronjob(action='list')

# Check status
cronjob(action='list')  # look for 'enabled' and 'state'
```

**Not receiving Telegram messages?**
```
# Verify Telegram connection
send_message(action='list')  # shows available channels
```

**Want to manually trigger a briefing now?**
```
# Morning briefing equivalent
mcp_jarvis_trader_get_briefing(symbol='MES')
mcp_jarvis_trader_get_positions()
mcp_jarvis_trader_get_safety_status()
```

---

**Last updated:** 2026-04-22  
**Status:** Live and operational  
**Contact:** HERMES via Telegram
