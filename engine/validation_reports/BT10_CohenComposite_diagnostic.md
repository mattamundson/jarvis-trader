# BT-10: Cohen MES Composite — Diagnostic Report
**Run:** 2026-06-02 07:35 UTC  
**Strategy:** VWAP + ORB + STC Composite, Regime-Adaptive Weights  
**Data:** SPY 1h — 5,082 bars — 2023-07-05 → 2026-06-01  
**Config:** entry_threshold=0.55, ADX≥25, stop=0.90×ATR, T1=1.50×ATR, T2=2.618×ATR

---

## Results Summary

| Metric | BT-10 Result | Gate Threshold | Pass? |
|---|---|---|---|
| Trades | 135 (L:66 S:69) | — | — |
| Win Rate | 53.3% (L:59.1% S:47.8%) | ≥55% | ✗ |
| Profit Factor | 0.949 | ≥1.275 | ✗ |
| Sharpe | -0.381 | ≥1.5 | ✗ |
| Sortino | -0.846 | ≥1.0 | ✗ |
| Calmar | -0.112 | ≥0.5 | ✗ |
| Max DD | 10.2% ($1,101) | ≤15% | ✓ |
| CAGR | -1.1% | — | — |
| Total Return | -3.2% | — | — |
| Consecutive Losses | 4 | ≤8 | ✓ |
| Skew | -0.154 | ≥-1.5 | ✓ |
| Gain/Pain | 0.949 | ≥0.50 | ✓ |

**Gates Passed: 4/10 — FAIL**

### Gate v2
| Metric | Value | Threshold |
|---|---|---|
| PF Bootstrap CI (90%) | 0.693 | ≥1.10 |
| P(Edge > 0) | 38.4% | ≥95% |
| DSR | 0.101 | ≥0.50 |
| **Gate v2 Verdict** | **FAIL** | — |

---

## Comparison: BT-3 → BT-4 → BT-10

| Metric | BT-3 (STC alone) | BT-4 (Phase gate) | BT-10 (Composite) |
|---|---|---|---|
| N Trades | 321 | 132 | 135 |
| Win Rate | 48.3% | 52.3% | 53.3% |
| Profit Factor | 1.028 | 1.275 | 0.949 |
| Sharpe | 0.083 | 0.744 | -0.381 |
| Max DD | -$30,798 | -$13,928 | -$1,101 |
| Long WR | 55.4% | ~55% | 59.1% |
| Short WR | 41.5% | ~41% | 47.8% |
| Gate v2 | FAIL | FAIL | FAIL |

**Notable:** Max DD improved dramatically (composite structure + ADX gate contained losses), but Sharpe went negative because R:R collapsed — avg stop loss $102.89 vs avg T1 win $79.28.

---

## Root Cause Analysis

### Problem 1: T1 Target Unreachable Intraday (PRIMARY)
- SPY 1h median ATR14 = **$1.95**
- T1 distance at 1.50×ATR = **$2.92** = **0.51% move** from entry
- SPY median intraday range = ~0.60–0.80%
- EOD closes represent **49% of all exits** (66/135 trades) — position never reaches T1
- EOD exits average +$31.28 (profitable) → the edge IS there, but target is too far
- Result: only 14% of trades exit at T1; stops eat 32% of trades at avg -$102.89

**Fix:** Reduce T1 to 1.0×ATR → R:R = 1.11. Better: drop EOD constraint + hold 1–3 days for T1.

### Problem 2: Regime Detection Collapse (SECONDARY)
- SPY 1h bars: **TRENDING = 84.7%**, RANGING = 15.0%, VOLATILE = 0.3%
- This reduces the composite to near-STC-only behavior (STC weight=0.60 in TRENDING)
- ORB and VWAP are effectively decorative (STC alone triggers at score=0.60 ≥ 0.55)
- Fix: Use ADX bands to distinguish Trending vs Ranging more granularly, or switch to a 3-tier volatility-adjusted regime.

### Problem 3: Short Side Structural Drag
- Short WR = 47.8%, Short PF = 0.882, Short total PnL = **-$296.17**
- Long WR = 59.1%, Long PF ≈ 1.009, Long total PnL = **+$25.89**
- SPY is structurally bullish (2023–2026 bull run); short STC crosses are counter-trend
- Net: shorts are destroying edge built by longs
- Fix: **Long-only mode** or short gating with VIX ≥ 20 / EMA50 < EMA200 only

### Problem 4: ADX Filter Is Over-Selective on SPY
- ADX ≥ 25 removes many valid STC crosses in RANGING/low-momentum sessions
- SPY 1h ADX median ≈ 18–22; threshold of 25 accepts only trending bursts
- 164 raw signals → 135 completed trades → ADX filtered ~18% of entries
- The filtered entries may actually have better R:R (less competition from trend momentum)

---

## Path Forward: What Works and What to Fix

### Option A: Long-Only + Overnight Hold (Recommended)
- Drop short entries entirely — SPY 2023–2026 structural bull
- Allow position to hold 1–3 days (remove EOD close, use trailing stop post-T1)
- Expected: WR ≈ 59–62%, PF ≈ 1.3–1.6, Sharpe ≈ 0.8–1.2
- Implementation: `eod_close=False`, `trailing_stop=True`, `trailing_post_t1=True`

### Option B: Tighter T1 + Partial Exit Optimization
- T1 = 0.75×ATR (R:R = 0.83 gross; with 53% WR, edge ≈ break-even)
- Better: T1 = 1.0×ATR, T2 = 2.0×ATR, allow 2-bar hold after T1
- Problem: R:R < 1.0 is a structural floor — can't Kelly-optimize a negative EV game
- Not recommended as primary fix

### Option C: Composite Score Raise + STC + ORB Confluence Required
- Require both STC AND ORB to fire (long_score ≥ 0.90 in TRENDING = STC + ORB both active)
- Reduces N from 135 → ~30–40 trades but expected higher WR and larger PnL per trade
- ORB trades (morning breakouts) have inherently better intraday follow-through
- Expected: WR ≈ 60–65%, but N too small for Gate v2 statistical validity

### Option D: Switch to MES Daily or Weekly Bars
- MES 1d data exists (1,108 bars) — daily STC is more meaningful for trend-following
- 1.50×ATR target on a daily ATR is ~$15–25/bar → achievable in 2–5 day moves
- More consistent with Strategy C+ swing philosophy
- Recommended for systematic implementation

---

## Verdict for BT-10

**Status: FAIL — 4/10 gates, Gate v2 FAIL**

The composite architecture is structurally sound, but three implementation issues prevent profitability on SPY 1h with current parameters:

1. **T1 target is too far** for intraday completion → 49% of trades forced to EOD exit
2. **Short entries are structurally unprofitable** in a bull regime → drag of -$296 on shorts vs +$26 on longs
3. **Regime detection defaults to TRENDING** on SPY (normATR median 0.29%, well below 2% threshold) → ORB/VWAP composite layer provides near-zero incremental value

**Next prescribed run: BT-10b** — Long-only variant with overnight hold + trailing stop + T1=1.0×ATR.  
Expected to pass gates: win_rate ≥55%, max_dd ≤15%, consec_losses ≤8.  
Still at risk: Sharpe ≥1.5 (hard bar), exposure ≥15% (few trades).

---

## Files Generated
- `BT10_CohenComposite_trades.csv` — 135 trade records
- `BT10_CohenComposite_validation.json` — full metrics + Gate v2
- `BT10_CohenComposite_summary.csv` — one-row Gate v2 tracker
- `BT10_CohenComposite_diagnostic.md` — this report

## Cumulative BT Progress
| BT | Strategy | WR | PF | Sharpe | Gates | Verdict |
|---|---|---|---|---|---|---|
| BT-3 | STC standalone | 48.3% | 1.028 | 0.083 | 0/4 | FAIL |
| BT-4 | STC + Phase gate | 52.3% | 1.275 | 0.744 | 2/4 | WEAK |
| BT-10 | Cohen Composite | 53.3% | 0.949 | -0.381 | 4/10 | FAIL |
| **BT-10b** | **Long-only + overnight** | **TBD** | **TBD** | **TBD** | **TBD** | **NEXT** |
