# JARVIS TRADER — Daily Operations Playbook

> Trading-focused daily routine replacing all GMS business operations. This is the complete
> day-in-the-life operating guide for Matt's trading workflow powered by JARVIS TRADER.

**Market reference (all times Central Time):**
- Futures pre-market: 6:00am CT
- **JARVIS morning brief: 6:30am CT** (2 hours before RTH)
- RTH open: 8:30am CT
- RTH close: 3:00pm CT
- After-hours: 3:00pm–5:00pm CT

---

## Daily Routine — At a Glance

| Time (CT) | Task | Tier | Standing Order |
|-----------|------|------|----------------|
| 6:30am | Pre-Market Intelligence Brief | T1 AUTO | SO-2 |
| 7:00am | Economic Calendar + FOMC/NFP/CPI check | T1 AUTO | T-13 |
| 7:30am | Futures positioning analysis + overnight gaps | T1 AUTO | SO-2 |
| 8:00am | Final pre-RTH regime check | T1 AUTO | SO-3 |
| 8:30am | RTH Open Alert + first-bar analysis | T1 AUTO | T-2 |
| Every 30min | Watchlist scan + signal detection | T1 AUTO | SO-3 |
| Continuous | P&L watch + kill switch monitoring | T1 AUTO | SO-6 |
| 3:45pm | Market Close Warning + position decisions | T1 AUTO | T-3 |
| 4:05pm | End of Day summary + journal | T2 NOTIFY | T-4 |
| Monday 7:00am | Weekly review + calendar preview | T1 AUTO | T-5 |

---

## 1. Pre-Market Intelligence Brief — 6:30am CT

*Replaces: GMS morning briefing. Fires 2 hours before RTH open.*

JARVIS TRADER automatically builds and delivers a complete pre-market brief at 6:30am CT.
No action required — just read it.

### What the brief covers:

**A. Overnight Futures Snapshot**
- MES (Micro S&P 500) — current price, overnight range, change from prior close
- MNQ (Micro Nasdaq-100) — same metrics
- MCL (Micro Crude Oil) — directional context for risk-on/risk-off
- SPY / QQQ — correlation check vs futures

**B. Macro Environment (FRED data)**
- VIX — fear gauge: `<15 = low vol | 15-25 = normal | 25-35 = elevated | >35 = extreme`
- Yield curve (2Y/10Y spread) — direction signal: inverted = caution
- DXY (Dollar Index) — rising dollar = headwind for equities
- Any overnight macro surprises (foreign market moves >1%)

**C. Economic Calendar — Today's Events**
- FOMC decisions (2:00pm ET) → flatten before 1:00pm CT
- CPI/PPI prints (8:30am ET) → expect gap at open, wait 5 min
- NFP/jobs data (8:30am ET, first Friday) → high-volatility open
- Treasury auctions, Fed speaker remarks, earnings

**D. Overnight Sentiment (Reddit/Finnhub scan)**
- ES/NQ retail sentiment score (bullish/bearish lean from r/wallstreetbets, r/stocks)
- Any black swan news or major geopolitical events overnight
- Institutional flow signals from Finnhub

**E. Open Positions Review** (if any overnight holds)
- Current unrealized P&L on any open positions
- Distance to stop loss in ticks + dollars
- Decision needed: hold or close before RTH?

**F. Risk Status**
- Daily P&L baseline: starts at $0, resets each session
- Kill switch: INACTIVE (green) / ACTIVE (red — no entries)
- Drawdown from equity peak: X% of -10% limit

**G. Regime Pre-Assessment**
- Yesterday's final regime: TRENDING/RANGE_BOUND/EXHAUSTED
- Overnight directional bias based on gap and macro

### Delivery format:
```
JARVIS TRADER — Pre-Market Brief | [DATE] 6:30am CT

━━━ FUTURES ━━━
MES:  [PRICE] | [+/- POINTS] ([+/- %]) | Overnight range: [LOW-HIGH]
MNQ:  [PRICE] | [+/- POINTS] ([+/- %])
MCL:  [PRICE] | [+/- POINTS]
VIX:  [LEVEL] — [INTERPRETATION]

━━━ MACRO ━━━
Yield curve: [2Y/10Y spread] — [NORMAL/INVERTED/FLAT]
DXY: [LEVEL] — [RISING/FALLING/STABLE]

━━━ CALENDAR ━━━
[HIGH IMPACT events or "Clear calendar today"]

━━━ POSITIONS ━━━
[Open positions or "No overnight positions — clean slate"]

━━━ RISK ━━━
Kill switch: INACTIVE | Daily P&L: $0 | Drawdown: -[X%]

━━━ BIAS ━━━
Pre-market directional lean: [BULLISH/BEARISH/NEUTRAL]
Recommended approach: [NORMAL/REDUCED SIZE/AVOID until X]

RTH opens in 2 hours. Standing by for regime confirmation.
```

---

## 2. Pre-RTH Preparation Window — 7:00am–8:30am CT

Tasks JARVIS TRADER handles automatically during this window:

### 7:00am — Economic Deep Dive
- If high-impact event today (FOMC/CPI/NFP): surface full playbook
- FOMC day rule: flatten positions by 1:00pm CT
- NFP/CPI rule: no new entries within 5 min of print — wait for first-bar close

### 7:30am — Futures Analysis
- Run `POST /analyze/technical` on MES (primary) + MNQ
- Full 5-layer regime check on 1h and 4h timeframes
- Identify key S/R levels: prior day high/low, overnight high/low, VWAP
- ATR calculation: current ATR dollar value per contract

### 8:00am — Final Pre-RTH Signal Check
- Run full pipeline on all watchlist symbols
- Check STC positioning: any instruments near OS (<15) or OB (>83)?
- If signal exists pre-market: note it, but **wait for RTH open** before acting
- Update ThinkOrSwim alerts if needed (verbal note to self via brief)

### 8:20am — Trade Plan for the Day
JARVIS surfaces the day's game plan:
```
TODAY'S TRADING PLAN — [DATE]

Primary instrument: MES [TIMEFRAME]
Current regime: [REGIME]
Directional bias: [LONG / SHORT / NEUTRAL]

Entry setup to watch: [STC oversold pullback / STC overbought short / HOLD — no setup]
Entry price zone: [APPROXIMATE LEVEL or "Not defined — wait for signal"]
Stop zone: [ATR-based, ~X points]
Target T1: [ATR-based, ~X points]
R:R: [X.XX]:1

Position sizing: [1 contract / 2 contracts / REDUCED — Liberation Day rule active]
Risk per trade: [X% of account = $X]

High-impact event: [YES — reduce size / NO — normal]
Liberation Day active: [YES: 0.5% risk / NO: 1.0% risk]
```

---

## 3. RTH Open — 8:30am CT

SO-T2 fires automatically at market open.

### Open Routine (hands-off — JARVIS handles):
1. RTH Open Alert fired with pipeline status
2. **5-minute rule**: No action on first 5 minutes (8:30–8:35am CT) — high noise
3. First bar analysis (8:35am CT): Run pipeline on opening 5-min bar
4. If opening gap >0.5%: note in session log, adjust ATR targets if needed
5. Run SO-3 first scheduled scan at 8:30am CT

### What Matt sees at open:
```
RTH OPEN — 8:30am CT

MES at open: [PRICE] | Gap from prior close: [+/- POINTS]
Opening regime: [TRENDING_UP / TRENDING_DOWN / RANGE_BOUND / EXHAUSTED]
STC at open: [VALUE]

Pipeline status: RUNNING — scanning every 30 minutes
First-bar rule: Active — recommending no entries until 8:35am CT

[If open position]: Position is LIVE — stop at [PRICE], T1 at [PRICE]
[If kill switch]: ⛔ KILL SWITCH ACTIVE — no entries until deactivated
```

---

## 4. Intraday Monitoring — 8:30am–3:00pm CT

### Every 30 Minutes (SO-3 Automated):
- Full pipeline run on all watchlist symbols
- STC evaluation + regime filter
- Results: BUY / SELL / HOLD per symbol
- Non-HOLD signals: WhatsApp alert dispatched (SO-4)
- Regime changes: T-20 fires immediately

### Position Management During RTH:

**Active trade management** (manual — Matt decides, JARVIS informs):
- JARVIS provides real-time distance to stop and target on request (T-15)
- Partial profits at T1 (50% off, trail the rest) — surfaced as a suggestion, not executed
- Scale-out rule: When T1 hit, move stop to breakeven on remainder

**Adding to winners** (Tier 3 — confirm first):
- Only in confirmed TRENDING regime
- Never add when STC is above 50 (on longs) — chasing
- Maximum 2 contracts total (hardcoded safety limit)

**When to sit out** (JARVIS flags these automatically):
- Regime = EXHAUSTED → T-20 fires, suggests stepping aside
- VIX > 25 → T-23 fires, suggests 1-contract max
- 3+ consecutive losses → T-12 Liberation Day rule activates
- FOMC/CPI in <30 min → T-13 warns to flatten

### Intraday Alerts JARVIS Auto-Surfaces:
| Alert | Trigger | Action |
|-------|---------|--------|
| BUY/SELL signal | STC + regime aligned | WhatsApp + JARVIS surface |
| Regime change | Regime flips | Warning in chat |
| Stop approach | Price within 30% of stop | Suggestion to tighten |
| Daily loss -1.6% | 80% of circuit breaker | Warning + options |
| VIX spike >25 | Fear elevated | Reduce size suggestion |
| Schedule missed | No scan in 45 min | Surface + offer manual scan |

---

## 5. Market Close Preparation — 3:45pm CT

T-3 fires automatically 15 minutes before RTH close.

### Close Routine:

**If open positions exist:**
- Decision prompt: Hold overnight (max 1 contract) or close?
- Overnight holding criteria: Trending regime + position at <50% to target
- Close rule: If stop is <20 ticks away, close — don't hold with tight stop overnight

**If no open positions:**
- Clean close — nothing to action
- Review signals missed today (if any HOLD prevented action)

**After-hours window (3:00–5:00pm CT):**
- MES continues trading — signals can still fire
- Reduced liquidity: wider spreads, don't size up
- Futures close at 5:00pm CT for daily settlement

---

## 6. End of Day Summary — 4:05pm CT

T-4 fires automatically 5 minutes after RTH close. JARVIS builds and delivers the EOD journal.

### EOD Summary includes:
```
━━━ END OF DAY SUMMARY — [DATE] ━━━

PERFORMANCE:
Daily P&L:     $[X] ([X%]) — [ABOVE/BELOW/AT breakeven]
Trades taken:  [N] ([W] wins / [L] losses) — Win rate: [X%]
Best trade:    [SYMBOL] +$[X] | Worst: [SYMBOL] -$[X]
Signals fired: [N] total (BUY: [N] / SELL: [N] / HOLD skipped: [N])

RISK SUMMARY:
Peak daily loss:   -[X%] (limit: -2.0%) — [COMFORTABLE/CLOSE]
Current drawdown:  -[X%] from peak (limit: -10.0%)
Kill switch:       [Never triggered / Triggered at TIME, deactivated at TIME]
Liberation Day:    [Active: [N] consecutive losses / Inactive]

REGIME REVIEW:
Opening regime:    [REGIME]
Closing regime:    [REGIME]
Changes today:     [N regime shifts at TIME, TIME]

TOMORROW:
Key calendar events: [LIST or "Clear"]
Pre-market brief:    Scheduled for 6:30am CT
Carry-forward notes: [Any open positions + overnight rules]
```

### Post-Market Tasks (manual — 5-10 min):
1. **Trade journal entry** — JARVIS drafts, Matt reviews (Tier 1)
   - Record: entry reasoning, exit, what worked, what didn't
   - Tag: regime, setup quality, execution quality
2. **ThinkScript adjustment** (if needed) — review if any levels need updating
3. **Tomorrow prep** — check economic calendar (FOMC/CPI/NFP next day?)

---

## 7. Weekly Review — Monday 7:00am CT

T-5 fires every Monday morning, layered on top of T-1 pre-market brief.

### Weekly Review covers:
```
━━━ WEEKLY REVIEW — Week Ending [FRIDAY DATE] ━━━

LAST WEEK PERFORMANCE:
Total P&L:      $[X] ([X%])
Total trades:   [N] | Win rate: [X%] | Profit factor: [X.XX]
Best day:       [DAY] +$[X] | Worst day: [DAY] -$[X]
Signals:        [N] total (BUY: [N] / SELL: [N] / HOLD: [N])

vs BACKTEST TARGET (MES 1h):
Profit Factor:  Target 5.27 | This week: [X.XX] — [TRACKING/BELOW/ABOVE]
Sharpe (4-wk):  Target 4.16 | Rolling: [X.XX]

REGIME SUMMARY LAST WEEK:
Primary regime: [TRENDING/RANGE_BOUND/EXHAUSTED — % of week each]
VIX range:      [LOW] – [HIGH] | Avg: [X.X]

THIS WEEK OUTLOOK:
Key events: [LIST — FOMC, CPI, NFP, major earnings]
Macro bias:  [BULLISH/BEARISH/NEUTRAL from yield curve + DXY]
Recommended sizing: [NORMAL / REDUCED — reason]
Liberation Day: [Active (continue 0.5% risk) / Resolved]
```

### Weekly Maintenance Tasks (15 min):
1. **Backtest comparison** — compare live performance vs backtest baseline
2. **Strategy param review** — are STC / ATR / regime thresholds still optimal?
3. **Watchlist audit** — add/remove symbols? (Tier 3 — confirm first)
4. **Risk limit review** — are daily/drawdown limits still appropriate?
5. **ThinkScript studies** — any new indicators to test this week?

---

## 8. Standing Orders — Complete Reference

These run automatically. No action needed from Matt.

| ID | Name | When | What |
|----|------|------|------|
| **SO-1** | Health Monitor | Always | Polls engine every 60s; WhatsApp if down 2× |
| **SO-2** | Market Open Brief | Trading days | Builds pre-market data cache by 6:00am CT |
| **SO-3** | Watchlist Scan | Mon–Fri 8:30am–3pm CT | Full pipeline every 30 min |
| **SO-4** | Signal Alert Dispatch | On BUY/SELL signal | WhatsApp alert with full signal breakdown |
| **SO-5** | Paper Trade Auto-Log | FundManager approved | Currently inactive (REQUIRE_HUMAN_APPROVAL=True) |
| **SO-6** | Daily P&L Watch | Always during hours | Tracks drawdown; fires warning at -1.6% |

---

## 9. Proactive Intelligence — What JARVIS Watches For You

These trigger automatically without asking:

### Critical (surfaces immediately, all day):
- **Kill switch activated** — T-6: shown on every response until cleared
- **Engine down** — T-10: shown before anything else until engine recovers

### High Priority Warnings:
- **BUY/SELL signal** — T-7: surfaced in JARVIS + WhatsApp dispatched
- **Daily loss at -1.6%** — T-8: approaching -2% circuit breaker
- **Drawdown at -8%** — T-9: approaching -10% max limit
- **3 consecutive losses** — T-12: Liberation Day protocol activates (0.5% risk)
- **FOMC day** — T-13: flatten reminder at 1:00pm CT
- **Regime change** — T-20: strategy implications surfaced
- **STC crosses 15 or 83** — T-21: primary entry trigger, pipeline auto-runs
- **Correlated positions** — T-22: concentrated risk warning
- **VIX > 25** — T-23: elevated vol, reduce sizing

### Context-Aware Auto-Loading:
- Mention any symbol → T-14: current price + last 3 signals loaded
- Ask about positions → T-15: full position P&L breakdown
- Mention risk/drawdown → T-16: safety status loaded
- Mention backtest → T-17: cached results surfaced
- Ask about regime → T-18: fresh 5-layer analysis run
- Mention options/Greeks → T-19: VIX context + STC bias surfaced

---

## 10. Trade Management Rules (Quick Reference)

### Entry Checklist (JARVIS runs this automatically on each signal):
- [ ] STC < 15 (long) or > 83 (short) ✓
- [ ] Regime = TRENDING (not EXHAUSTED or RANGE_BOUND) ✓
- [ ] All 5 regime filter layers passing ✓
- [ ] Kill switch INACTIVE ✓
- [ ] Daily P&L > -1.6% (not approaching halt) ✓
- [ ] ATR stop defined (0.70x ATR from entry) ✓
- [ ] T1 target defined (1.50x ATR from entry) ✓
- [ ] R:R ≥ 1.5:1 ✓
- [ ] Not within 30 min of major economic event ✓
- [ ] Liberation Day rule: if 3+ losses, size = 0.5% risk ✓

### Position Sizing Formula:
```
Account equity × Risk % = Dollar risk
Dollar risk ÷ (Stop distance in ticks × Tick value) = Contracts

Example: $10,000 × 1.0% = $100 risk
MES stop: 10 ticks × $1.25/tick = $12.50/contract
$100 ÷ $12.50 = 8 contracts → capped at 2 (safety limit)
```

### ATR Reference (MES approximate):
- Normal vol (VIX 15-20): ATR ≈ 15-25 pts/day | Stop ≈ 8-12 pts
- Elevated vol (VIX 20-30): ATR ≈ 25-45 pts/day | Stop ≈ 15-25 pts
- Extreme vol (VIX >30): ATR ≈ 45-80 pts/day | Stop ≈ 30-50 pts

---

## 11. Emergency Protocols Quick Reference

| Situation | JARVIS Behavior | Matt's Action |
|-----------|-----------------|---------------|
| Daily loss -2% | Kill switch auto-activates (SafetyLayer) | Tier 3 confirmation to resume |
| Drawdown -10% | Kill switch auto-activates (SafetyLayer) | Full review before resuming |
| Engine down | T-10 on every response; restart instructions | `pm2 restart jarvis-trader` |
| Anomalous orders | Kill switch + CRITICAL alert | Investigate IB Gateway logs first |
| S&P circuit breaker Level 1 | Surface + note Liberation Day context | Evaluate at halt lift |
| 3+ correlated positions losing | EP-6 cascade advisory | Pause entries, review stops |

---

## 12. Options Trading — Roadmap Note

*Options monitoring is not yet integrated in JARVIS TRADER v1.1.0.*

What JARVIS CAN provide for options context right now:
- **VIX level** → proxy for IV environment (sell premium when VIX high, buy when low)
- **STC direction on underlying** → directional bias for calls vs puts
- **Regime** → trending = directional plays; choppy = premium selling favored
- **Social sentiment** → rough proxy for retail options flow

**Coming in future versions:**
- Delta/Gamma/Theta tracking per position
- IV rank per strike and expiration
- P50/POP calculations for short premium strategies
- Calendar vs vertical spread selector based on IV regime
- 0DTE / weekly expiration watchlist

---

## 13. ThinkScript Library Reference

JARVIS TRADER maintains 30+ ThinkScript studies. Use these in ThinkorSwim:

### Signal Indicators (import to TOS):
- `STC_Signal_Alert` — Schaff Trend Cycle with OS/OB arrows on chart
- `ATR_StopLoss_Dynamic` — live ATR stop and T1 target plotted on chart
- `JARVIS_Entry_Box` — highlights bars where all 5 regime layers pass

### Regime Filters (upper studies):
- `ADX_Regime_Filter` — ADX with trending/choppy color coding
- `VIX_Regime_Overlay` — VIX on underlying chart (normalized)
- `Market_Breadth_Scanner` — A/D line and breadth context

### Risk Management (lower studies):
- `DailyPnL_Meter` — running daily P&L vs -2% limit
- `Drawdown_Gauge` — equity curve vs -10% max drawdown
- `Position_Size_Calculator` — enter account and risk %, get contract count

### Session Reference:
- `RTH_VWAP_Levels` — VWAP + 1/2 SD bands (primary S/R)
- `Opening_Range_Breakout` — first 30-min high/low marked
- `Overnight_Gap_Fill` — gap fill levels from prior close

---

## 14. Key Metrics to Track Weekly

| Metric | Target (Backtest) | Acceptable | Review Trigger |
|--------|-------------------|------------|----------------|
| Profit Factor | 5.27 | >2.0 | <1.5 for 2 weeks |
| Sharpe Ratio (rolling 4-wk) | 4.16 | >2.0 | <1.5 |
| Win Rate | ~36% | >30% | <25% |
| Max Drawdown | <8.3% | <10% | >7% — review sizing |
| Avg Winner / Avg Loser | 2.5:1 | >1.5:1 | <1.2:1 |
| Consecutive losses | N/A | <5 | 3 → Liberation Day rule |

---

## 15. Paper Trading Validation Checklist — April–May 2026

Current phase: **PAPER TRADING** (Phase 2 of 4)

| Phase | Status | Criteria |
|-------|--------|----------|
| Phase 1: Backtesting | ✅ COMPLETE | MES 1h PF 5.27, Sharpe 4.16 confirmed |
| Phase 2: Paper trading | ⏳ IN PROGRESS | 60 days, target PF >3.0, max DD <8% |
| Phase 3: Live micro ($500) | 📅 JUNE 2026 | IB Gateway connected, 3 contracts/day |
| Phase 4: Full deployment | 📅 Q3 2026 | $10K+ account, full automation |

### Paper trading "pass" criteria for live graduation:
- 60 consecutive trading days paper traded
- Profit Factor > 3.0 (vs 5.27 backtest — some degradation expected)
- Max drawdown < 8% (within backtest bounds)
- Win rate > 28% (vs 36% backtest)
- At least 40 closed trades (sufficient sample size)
- No kill switch breaches due to position sizing errors
- IB Gateway integration tested and confirmed

---

*JARVIS TRADER v1.1.0 | Daily Routine v1.0 | March 2026*
*Pre-market brief: 6:30am CT | RTH: 8:30am–3:00pm CT | Engine: localhost:8010*
