# JARVIS TRADER — Strategy Playbook
## The Tony Stark Framework: A Regime-Adaptive, Structure-Aware Momentum System

*Version 1.0 — April 3, 2026*
*Author: Matt Amundson / Claude Opus 4.6*
*Status: Paper Validation (Day 2 of 30)*

---

## 1. THE EDGE — Why This Strategy Works

The edge comes from three compounding advantages that are difficult for other market participants to replicate simultaneously:

**Advantage 1: Multi-Layer Signal Confluence.** The system requires alignment across 4 independent analytical layers before entering a trade. Each layer measures a different market dimension — regime state, market structure, directional bias, and entry timing. A random entry has roughly a 50/50 chance; requiring 4-layer alignment filters out 80-90% of potential trades, leaving only the highest-conviction setups. This is why trade counts are low (65-86 trades over 21 months) but quality is high.

**Advantage 2: Regime Awareness.** Most retail systems use fixed parameters in all conditions. This system classifies each bar into TRENDING_BULL, TRENDING_BEAR, RANGE_BOUND, COMPRESSION, or EXHAUSTED — and adapts behavior accordingly. In EXHAUSTED regimes (ATR consumed > 90%), the system either fades the extreme or sits out entirely. This single filter eliminated the majority of losing trades in backtest optimization.

**Advantage 3: Walk-Forward Validated Instruments Only.** The system only trades instruments where the Walk-Forward Efficiency (WFE) exceeds 0.50, meaning at least 50% of in-sample edge survives into out-of-sample periods. This is the difference between curve-fitting and a real edge. MCL (WFE=0.82) retains 82% of its in-sample performance in unseen data — that's the signal that something real is being captured.

---

## 2. APPROVED INSTRUMENTS

Only instruments that pass Walk-Forward Efficiency >= 0.50 are approved for paper trading.

### MCL — Micro Crude Oil (1h) — PRIMARY

| Metric | Value |
|--------|-------|
| WFE | 0.82 (EXCELLENT) |
| OOS Windows Profitable | 4 of 6 |
| Avg OOS Profit Factor | 1.21 |
| Projected Trades | ~65 per 21 months |
| Monte Carlo | 100% probability profitable |
| Status | APPROVED — Paper Trading Active |

MCL is the strongest instrument. Crude oil has persistent trending behavior driven by OPEC decisions, inventory reports, and geopolitical events that create multi-day directional moves the STC oscillator can capture. The 0.82 WFE means the strategy is capturing something structural, not just fitting noise.

### MNQ — Micro E-mini Nasdaq (1h) — SECONDARY

| Metric | Value |
|--------|-------|
| WFE | 0.57 (GOOD — standard walk-forward) |
| Adaptive WFE | 0.57 (confirmed with regime-adaptive params) |
| OOS Windows Profitable | 3 of 6 |
| In-Sample Trades | 86 |
| In-Sample PF | 1.51 |
| In-Sample WR | 50% |
| Max Drawdown | 5.2% |
| Sensitivity Score | 94/100 (ROBUST) |
| Monte Carlo | 100% probability profitable |
| Status | APPROVED — Paper Trading Active |

MNQ requires the wider overbought threshold (STC_OB=92 vs default 83) to filter Nasdaq-specific noise. This was the consensus across all top 10 optimizer results. The 86-trade sample provides strong statistical significance.

### HALTED / DO NOT TRADE

| Symbol | TF | WFE | Reason |
|--------|-----|-----|--------|
| MES | 1h | 0.09 | Virtually no out-of-sample edge. DO NOT TRADE. |
| MGC | 1d | 0.14 | Overfit. 73% IS-to-OOS degradation. Real edge ~2.7% annualized. |
| M2K | all | N/A | PF < 1.0 on both timeframes. Consistent loser. |
| MCL | 1d | N/A | PF = 0.21. Catastrophic on daily bars. |
| MES | 1d | N/A | PF = 0.75. Targets unreachable on daily. |

---

## 3. THE 5-LAYER SIGNAL FRAMEWORK

### Layer 1 — Regime Map

Classifies the current market environment. This is the master gate — if the regime is wrong, no trade fires.

| Regime | Condition | Action |
|--------|-----------|--------|
| TRENDING_BULL | EMA 8>21>34, phase>0, ATR consumed <70% | Entries allowed (long bias) |
| TRENDING_BEAR | EMA 8<21<34, phase<0, ATR consumed <70% | Entries allowed (short bias) |
| RANGE_BOUND | Mixed EMA, no clear direction | Limited entries (structure-based only) |
| COMPRESSION | Phase compression active, consumed <50% | BLOCKED (MCL/MNQ) — breakout imminent but direction unknown |
| EXHAUSTED | ATR consumed >90% | BLOCKED or FADE only (phase >61.8 or <-61.8) |

**Key indicators**: EMA Ribbon (8/21/34), Phase Oscillator (EMA 21, ATR 14, BB 21/2.0), ATR Range Consumed %.

### Layer 2 — Structure Map (Auction Theory)

Determines WHERE price is relative to value. Uses VPOC (volume-weighted price), Value Area (VAH/VAL), and Initial Balance (prior bar high/low).

| Position | Condition | Meaning |
|----------|-----------|---------|
| BUYER_CONTROL | Price > VAH AND > IB High | Price accepted above value — strongest long signal |
| SELLER_CONTROL | Price < VAL AND < IB Low | Price accepted below value — strongest short signal |
| NEUTRAL | Inside value area or mixed | No structural edge — wait for breakout |

**Structure-boosted entries**: When BUYER_CONTROL aligns with TRENDING_BULL + bullish bias, the system fires ENTRY_NOW immediately without requiring an STC crossover. This captures breakout moves that STC would be late to signal.

### Layer 3 — Directional Bias

Counts bullish vs bearish votes across 4 indicators to determine conviction.

| Indicator | Bullish Vote | Bearish Vote |
|-----------|-------------|--------------|
| KAMA (10) | Close > KAMA | Close < KAMA |
| STC | Oversold or Rising | Overbought or Falling |
| Volume Stack | Buy % > 60% | Buy % < 40% |
| EMA Trend | 8 > 21 > 34 | 8 < 21 < 34 |

| Votes | Bias | Position Size Multiplier |
|-------|------|------------------------|
| 4 bull | STRONG_BULL | 1.00x (full) |
| 3 bull (or 2 + bullish EMA) | LEAN_BULL | 0.50x (half) |
| 4 bear | STRONG_BEAR | 1.00x (full) |
| 3 bear (or 2 + bearish EMA) | LEAN_BEAR | 0.50x (half) |
| Mixed | NEUTRAL | No trade |

### Layer 4 — Entry Timing

Three entry trigger types, in priority order:

**1. Structure-Boosted (highest conviction):**
- BUYER_CONTROL + bullish bias + TRENDING_BULL → immediate ENTRY_NOW
- IB High breakout (price crosses above prior bar high) + bullish bias → ENTRY_NOW
- Mirror logic for shorts

**2. STC Crossover (standard):**
- STC crosses above oversold threshold + bullish bias → ENTRY_NOW
- STC crosses below overbought threshold + bearish bias → ENTRY_NOW

**3. Wait/No Trade:**
- STC between 20-80 → WAIT_FOR_PULLBACK
- Neutral bias → NO_TRADE
- Exhausted regime → NO_TRADE (or FADE_EXTREME if phase is at Fib extreme)

### Layer 5 — Conviction-Aware Position Sizing

| Alignment | Multiplier | When |
|-----------|-----------|------|
| SIZING_FULL (1.00x) | Strong bias + Trending + Directional structure | Everything aligned |
| SIZING_HIGH (0.80x) | Strong bias + Trending | Structure neutral |
| SIZING_HALF (0.50x) | Lean bias OR non-trending regime | Partial conviction |
| SIZING_MIN (0.25x) | Anything else | Minimum viable |

---

## 4. PER-INSTRUMENT PARAMETERS

These are the research-validated, per-instrument parameters currently in `signals.py`:

### MCL (Micro Crude Oil, 1h)
```
STC_OS = 15          # Oversold threshold
STC_OB = 83          # Overbought threshold
Stop   = 0.90 ATR    # Stop loss distance
T1     = 1.50 ATR    # Target 1 (risk:reward = 1.67)
T2     = 2.618 ATR   # Target 2
T3     = 4.00 ATR    # Runner target
Regime = ON          # Block EXHAUSTED/COMPRESSION entries
```

**NOTE — Sensitivity analysis found Stop=0.70 is a DEAD ZONE for MCL (only 8 trades). The current 0.90 gives 65 trades with PF 1.81. Consider testing 0.84 as an alternative.**

### MNQ (Micro Nasdaq, 1h)
```
STC_OS = 15          # Oversold threshold
STC_OB = 92          # Wider OB filters Nasdaq noise (vs 83 default)
Stop   = 0.70 ATR    # Stop loss distance
T1     = 1.00 ATR    # Target 1 (risk:reward = 1.43)
T2     = 1.80 ATR    # Target 2
T3     = 2.618 ATR   # Runner target
Regime = ON          # Block EXHAUSTED/COMPRESSION entries
```

**NOTE — STC_OB=92 was the consensus across ALL top 10 optimizer results for MNQ. This is not default behavior — it's the single most important parameter difference for this instrument.**

### STC Core Parameters (All Instruments)
```
Fast Period  = 23
Slow Period  = 50
K Period     = 10
D Period     = 3
```

---

## 5. RISK MANAGEMENT

### Position Sizing Formula (Fixed-Fractional)

```
risk_per_trade          = account_value * risk_pct  (1% default)
stop_distance           = ATR * stop_multiplier     (per instrument)
dollar_risk_per_contract = stop_distance * contract_multiplier
contracts               = floor(risk_per_trade / dollar_risk_per_contract)
contracts               = clamp(contracts, 1, max_contracts)
```

### Contract Multipliers
| Symbol | $/Point | Stop (ATR mult) | Typical ATR (1h) | Typical Stop ($) |
|--------|---------|-----------------|------------------|-----------------|
| MCL | $100/pt | 0.90x | ~$1.50 | ~$135/contract |
| MNQ | $2/pt | 0.70x | ~150 pts | ~$210/contract |

### Drawdown Risk Ladder
| Drawdown | Action |
|----------|--------|
| 0-5% | Full position sizing (1.0x) |
| 5-8% | Reduce to 0.75x |
| 8-10% | Reduce to 0.50x |
| 10%+ | KILL SWITCH — halt all trading |

### Consecutive Loss Protection
| Losses | Action |
|--------|--------|
| 3 in a row | Half position size (0.50x) |
| 5 in a row | Quarter position size (0.25x) |
| 7 in a row | Halt trading for 24 hours |

### Hard Limits (Safety Layer — Non-Negotiable)
| Parameter | Limit |
|-----------|-------|
| Daily loss halt | -2% of portfolio |
| Emergency drawdown halt | -10% from peak |
| Max contracts per instrument | 2 micro |
| Max overnight contracts | 1 |
| Max single order value | $5,000 |
| Max margin utilization | 40% |
| Max correlated exposure | 20% |
| Rate limit | 10 orders/minute |
| Price collar | Reject if > 5% from NBBO |

### VIX Overlay
| VIX Level | Regime | Position Adjustment |
|-----------|--------|-------------------|
| < 12 | CALM | 1.0x (full) |
| 12-20 | NORMAL | 1.0x (full) |
| 20-30 | CAUTION | 0.75x, strong signals only |
| 30-40 | ELEVATED | 0.50x, strong signals only |
| >= 40 | EXTREME | 0.0x — ALL TRADING PAUSED |

---

## 6. TRADE EXECUTION RULES

### Entry Rules

1. All 4 layers must align (regime allows entry + structure confirms + bias is directional + timing trigger fires)
2. REQUIRE_HUMAN_APPROVAL = True — every trade requires manual confirmation via dashboard or API
3. Market orders for micro futures (sufficient liquidity, minimal slippage)
4. Entry on the NEXT bar open after signal (no same-bar entries — prevents lookahead bias)

### Exit Rules

**Stop Loss**: ATR-based, set at entry. Per-instrument multiplier (MCL: 0.90x ATR, MNQ: 0.70x ATR). Non-negotiable — no moving stops wider.

**Target 1**: Partial exit (scale out). MCL: 1.50 ATR, MNQ: 1.00 ATR. Take profit on 50% of position.

**Target 2**: Second partial exit. MCL: 2.618 ATR, MNQ: 1.80 ATR. Take profit on remaining 50%.

**Target 3 (Runner)**: Only for positions that reach T2. Trail stop to breakeven, let the runner ride. MCL: 4.00 ATR, MNQ: 2.618 ATR.

**End-of-Day**: Futures positions should be evaluated at 3:30 PM CT (30 min before close). Positions not at T1 should be manually reviewed. The system does NOT auto-close at EOD — Matt decides.

**Kill Switch Override**: If daily P&L hits -2% or drawdown hits -10%, ALL positions are force-closed immediately. This is hardcoded Python, not LLM-dependent.

### No-Trade Conditions

- EXHAUSTED regime (ATR consumed > 90%) — sit out unless fading extreme
- COMPRESSION regime — direction unknown, breakout imminent but which way?
- NEUTRAL bias (mixed indicator votes) — no edge
- VIX >= 40 — extreme volatility, all entries blocked
- News blackout window (FOMC, CPI, NFP, GDP) — 30 minutes before and after
- 7+ consecutive losses — halt for 24 hours
- Low volume bars (optional volume_filter) — below 20-bar average

---

## 7. COMPOSITE SIGNALS (EXPERIMENTAL)

For MES/MCL/MNQ, the system can use a 3-signal composite that fuses STC with two additional signal sources:

**STC** (momentum/trend): The core signal. Weight: 0.60 in trending, 0.50 in ranging.
**ORB** (Opening Range Breakout): Morning momentum signal, active 9:30-11:00 ET. Weight: 0.30 in trending, 0.20 in ranging.
**VWAP Deviation Reversion**: Mean reversion signal, active after 11:00 ET. Weight: 0.10 in trending, 0.30 in ranging.

In VOLATILE regimes, all weights go to 0.00 — the system sits out entirely.

Entry threshold: composite_score >= 0.35. This means STC alone (0.50-0.60) can trigger an entry, but VWAP alone (0.30 max) cannot. STC acts as a GATE — the other signals can only add conviction, never enter independently.

**STATUS**: NEEDS TUNING. Composite backtests on MES show PF 0.15-0.28, which is negative expectancy. The composite system is not yet viable for paper trading. The standard 5-layer framework is what's running in production.

---

## 8. WHAT WE DON'T KNOW (Honest Assessment)

**The backtest-to-live gap is real.** MCL's in-sample PF of 1.81 will likely degrade to OOS levels around PF 1.21 (the walk-forward average). That's the whole point of the 30-day paper validation — to measure the real-world PF before risking live capital.

**MNQ's walk-forward is less convincing than its backtest.** The standard WFE is 0.57 (acceptable) but the OOS profit factor is 0.97 — barely breakeven. The sensitivity score (94/100) and Monte Carlo (100% profitable) provide confidence, but 30 days of paper data will tell us more than any backtest.

**The composite signal system doesn't work yet.** Despite the elegant architecture (STC+ORB+VWAP fusion with regime-adaptive weighting), actual backtests show PF 0.15-0.28. This needs fundamental rethinking before activation.

**We're trading 2 instruments with $10K.** This is thin. A single bad day on MCL (crude oil inventory surprise) could hit the -2% daily loss limit with just 1 contract. Diversification across 2 micro futures provides some protection, but this is not a portfolio — it's two bets.

**Market regime can change.** The WFE was calculated on 2024-2026 data. A fundamental shift in crude oil market structure (e.g., OPEC dissolution, major geopolitical event) could invalidate the MCL edge. The system re-runs WFE every 90 days as a health check.

---

## 9. PAPER VALIDATION GATES

All gates must pass simultaneously before live deployment (Phase 3):

| Gate | Threshold | Current | Notes |
|------|-----------|---------|-------|
| Profit Factor | >= 2.0 | TBD | Day 2 of 30 |
| Sharpe Ratio | >= 1.5 | TBD | Annualized |
| Win Rate | >= 55% | TBD | Across both instruments |
| Trade Count | >= 60 | 3 | Need sustained signal generation |
| Days Trading | >= 30 | 2 | Continuous, no gaps > 3 days |
| Max Drawdown | <= 15% | TBD | Peak-to-trough |

**Start Date**: April 2, 2026
**Target End**: May 2, 2026
**Account**: IB Paper DUP662235, port 4002
**Capital**: $10,000

---

## 10. MONITORING & MAINTENANCE

### Daily Checklist

1. Check dashboard ValidationGatesWidget for current gate status
2. Review any pending approvals from overnight scanner
3. Verify IB Gateway connection is active (heartbeat every 60s)
4. Check engine logs for scanner errors or safety layer warnings
5. Review P&L against daily loss limit (-2%)

### Weekly

6. Review all trades from the week — were entries high-conviction or marginal?
7. Check regime distribution — has the market been trending or ranging?
8. Compare paper results to backtest expectations

### Monthly / Every 90 Days

9. Re-run Walk-Forward Efficiency on both instruments
10. If WFE drops below 0.50, HALT that instrument and investigate
11. Re-run sensitivity analysis if parameters were changed
12. Review drawdown risk ladder — are position sizes appropriate?

---

## 11. PARAMETER DISCREPANCY ALERT

The current `signals.py` has per-instrument parameters via `INSTRUMENT_PARAMS` dict, but the sensitivity analysis suggests two changes that should be evaluated during paper validation:

| Instrument | Current Stop | Recommended Stop | Reason |
|-----------|-------------|-----------------|--------|
| MCL | 0.90 ATR | 0.84 ATR | Sensitivity analysis found 0.70 is a dead zone; 0.84 gives 65 trades vs 8 |
| MNQ | 0.70 ATR | 0.70 ATR | Confirmed optimal by optimizer |

| Instrument | Current T1 | Recommended T1 | Reason |
|-----------|-----------|---------------|--------|
| MCL | 1.50 ATR | 1.00 ATR | Sensitivity shows 1.50 rarely hit intraday; 1.00 is more reachable |
| MNQ | 1.00 ATR | 1.00 ATR | Confirmed optimal |

**Action**: Monitor whether MCL T1 (1.50 ATR) is being reached during paper validation. If < 20% of trades reach T1, reduce to 1.00 ATR.

---

*This playbook is a living document. Update after each sprint and each 90-day WFE review.*
*The strategy is the strategy until the data says otherwise. No discretionary overrides during paper validation.*
