# JARVIS Pre-Market Briefing — Monday, April 20, 2026

**Generated:** 07:43 CT (08:43 ET) | **Session:** Pre-Market (4:00–9:30 AM ET)
**Engine:** Running (v1.1.0) | **IBKR:** Offline (Polygon fallback) | **Paper Mode:** Active

---

## DATE AND SESSION

- **Date:** Monday, April 20, 2026
- **Time to equity open:** ~47 minutes (9:30 AM ET)
- **Time to crude pit open:** ~17 minutes (9:00 AM ET)
- **CME Futures:** Trading now (overnight session active)
- **Scheduled releases today:** No major US economic releases confirmed for today.
  Next significant data expected mid-week. Monitor for any surprise Fed speaker commentary.

---

## MACRO ENVIRONMENT — NEUTRAL/BEARISH LEAN

| Indicator       | Value    | Read        |
|-----------------|----------|-------------|
| VIX             | 19.27–20.0 | ⚠️ Elevated — caution zone, not panic |
| Fed Funds Rate  | 4.33%    | Restrictive — no cuts priced near-term |
| 10Y Yield       | 4.30%    | Elevated, pressure on growth names |
| Unemployment    | 4.1%     | Neutral |
| S&P Futures     | 7,132 (-0.41%) | Mildly bearish open |
| NDX Futures     | 26,721 (-0.39%) | Soft |
| WTI Crude       | ~$89.81  | Volatile — rebounding from $84 low |

**Read:** Macro is cautious. VIX near 20 after spiking Friday (+10.24%) signals hedging activity
returning. Futures are slightly negative Monday morning, fading Friday's risk-on rally. Crude has
been whipsawed by geopolitical events — high noise environment.

---

## TOP HEADLINES

- **Iran / Strait of Hormuz:** Iran declared the Strait of Hormuz "completely open" on Friday, sparking
  an oil selloff; WTI dropped 11% to ~$84 mid-week before rebounding to ~$90 Monday. Deal speculation
  driving crude volatility in both directions.

- **US-Iran War / Peace Speculation:** Risk-on Friday rally (+1.20% S&P) driven by mounting speculation
  of a deal to end the US-Iran conflict. Status Monday unclear — watch for headlines.

- **TSMC AI Demand Beat:** TSMC raised its 2026 revenue forecast citing strong AI chip demand; chipmakers
  led the Nasdaq rebound Thursday-Friday. Positive for MNQ longer term.

- **Equity Highs Friday:** S&P 500 and Nasdaq 100 posted new all-time highs on Friday. Monday is fading
  those gains slightly in pre-market — normal consolidation or early sign of exhaustion.

- **VIX Spike:** VIX up 10.24% despite equity rally — options market hedging into Monday. Watch for
  follow-through volatility at open.

---

## MCL POSTURE — DATA UNAVAILABLE

- **Status:** ⚠️ Technical analysis endpoint returned 500 error
- **Root cause:** IB Gateway offline (port 4002 refused); CSV cache is 324 days stale (last bar
  2025-05-30); Polygon fallback unavailable for MCL futures
- **Corey Auction:** neutral bias, signal=0.00, conf=0.47 (commentary-only quality)
- **Stale reference price:** $94.48 (CSV cache — NOT current; WTI web data suggests ~$89.81)
- **Active setup:** None confirmed. Do NOT trade MCL without live data feed
- **Action:** IB Gateway must be running on port 4002 for live signals. Start TWS/Gateway before session

---

## MNQ POSTURE — DATA DEGRADED

- **Status:** ⚠️ Technical analysis endpoint returned 500 error
- **Root cause:** IB Gateway offline; CSV cache 20 days stale (last bar 2026-03-31); Polygon unavailable
- **Corey Auction:** neutral bias, signal=0.00, conf=0.46 (commentary-only quality)
- **Stale reference price:** $23,794 (CSV cache — NOT current; web data shows ~26,725)
- **Regime:** Cannot determine — no fresh bars to compute STC or momentum
- **Active setup:** None confirmed. Do NOT trade MNQ without live data feed
- **Action:** Restore data layer (IB Gateway port 4002 or Polygon subscription for futures)

---

## WATCH LIST

1. **Iran peace deal headlines** — any confirmation or denial will move crude ±3-5%. MCL is not
   tradeable without live data but monitor for context.

2. **VIX behavior at open** — if VIX stays elevated (>20) as equities open, Friday's rally was a
   bull trap. If VIX drops back below 18, risk-on resumes. This determines MNQ directional bias.

3. **Nasdaq 9:30 price action** — NQ/MNQ is near all-time highs after the TSMC-driven rally.
   Watch for gap fill vs. continuation. A gap-down open that fills quickly is bullish; sustained
   selling below Friday's low is a warning.

---

## RISK NOTE

- **VIX elevated (~20):** Above normal levels; expect wider-than-usual intraday swings
- **Data layer degraded:** Both MCL and MNQ signals are OFFLINE. Engine cannot generate valid
  trade signals today until IB Gateway (port 4002) is connected or Polygon futures data is restored
- **Crude whipsaw risk:** Oil prices have swung 11% in 3 days on geopolitical noise. MCL is high
  risk even if data were available
- **LIVE_TRADING_ENABLED = False** — paper observation only. No trades will execute automatically

---

## ENGINE STATUS

| Component       | Status |
|-----------------|--------|
| Engine          | ✅ Running (v1.1.0, port 8010) |
| IB Gateway 4002 | ❌ Offline |
| Polygon.io      | ✅ Connected (equities only) |
| Safety Layer    | ✅ Active — daily P&L: +$180.00, equity: $10,330 |
| Kill Switch     | ✅ Armed (-2% daily / -10% drawdown) |
| Paper Mode      | ✅ Enforced |

---

*Briefing generated by JARVIS automated pre-market agent. Paper trading observation only.*
*No trade recommendations. Signal posture based on available data; MCL/MNQ signals unavailable today.*
