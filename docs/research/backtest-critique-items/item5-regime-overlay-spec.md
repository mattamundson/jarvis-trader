# Critique Item 5 (closed): Coarse trend/range regime overlay spec

**Status:** closed · **Closes:** `docs/research/backtest-critique-mes_sma_trend_vix_pctile-2026-09-24.md` open item 5
**Date closed:** 2026-09-26 · **Merged via:** PR #(TBD)

---

## What this records

The backtest critique for `mes_sma_trend_vix_pctile` noted that the regime split is by volatility tier only (unblocked, +Crisis, +Crisis+HighVol, +HighVol), and suggested considering a coarse trend/range regime overlay in addition to the volatility-tier split for the regime-split gate.

This document records a concrete coarse trend/range overlay spec, explains why it is a useful addition, and documents why the volatility-tier split already satisfies the regime-split gate (so this is an enhancement, not a gating fix).

## Current regime split (volatility-tier only)

The strategy's current regime split reports OOS PF by tier-block combination:

| Tier block | OOS PF | Trade count | Notes |
|---|---|---|---|
| Unblocked (all regimes) | 1.648 | 122 | Baseline |
| +Crisis block | 1.494 | 112 | Crisis regimes excluded |
| +Crisis+HighVol block | 1.479 | 89 | Crisis + HighVol excluded |
| +HighVol block | 1.666 | 99 | HighVol-only block, strongest |

Edge persists across all blocks. The HighVol-only block is the strongest. This satisfies the JARVIS regime-split gate: the strategy's edge is demonstrated across multiple volatility regimes.

However, the split is purely by volatility. It does not distinguish between trending and ranging markets within the same volatility tier. A 1h SMA-trend strategy like this one should, in principle, perform differently in trending vs ranging conditions — and documenting that split would strengthen the regime analysis.

## Coarse trend/range overlay spec

### Definition

Add a binary trend/range classification to the regime split, defined at the 1h bar level using a coarse, regime-agnostic method:

**Option A (ADX-based, recommended):**
- **Trend:** ADX(14) > 25 on the MES 1h chart — the market is exhibiting directional movement.
- **Range:** ADX(14) ≤ 25 — the market is oscillating without a clear trend.
- **Buffer:** ADX between 20 and 25 is a "gray zone" — count it as ambiguous and report it separately, or assign it to the closer category.

**Option B (SMA slope-based, simpler):**
- **Trend:** Price above SMA-200 AND SMA-60 > SMA-200 AND SMA-60 slope (20-bar linear regression) is positive — the trend filter is active and strengthening.
- **Range:** Price below SMA-200 OR SMA-60 < SMA-200 OR SMA-60 slope is flat/negative — the trend filter is inactive or weakening.
- This overlaps with the strategy's own entry rules, so it's less independent than ADX.

**Option C (HV/RV ratio, volatility-adjusted):**
- **Trend:** HV(20)/RV(20) ratio > 1.2 — realized volatility is expanding faster than historical, suggesting directional movement.
- **Range:** HV(20)/RV(20) ratio ≤ 1.2 — volatility is contracting or stable, suggesting range-bound conditions.
- This is more orthogonal to the existing volatility-tier split.

### Recommendation: ADX-based (Option A)

ADX is the cleanest coarse trend/range classifier for this purpose because:

- It is independent of the strategy's own SMA/ATR parameters (no look-ahead or self-reference risk).
- It is widely used in the quantitative finance literature for trend/range classification.
- It captures the directional-vs-oscillatory distinction that matters for a trend-following strategy.
- It adds a genuinely new axis to the regime analysis without re-using the strategy's own signals.

### 2×2 regime matrix

With the ADX-based overlay, the regime split becomes a 2×2 matrix:

| | Low/Moderate Volatility | High Volatility |
|---|---|---|
| **Trend (ADX > 25)** | Tier 1 | Tier 2 |
| **Range (ADX ≤ 25)** | Tier 3 | Tier 4 |

Each cell would report OOS PF, trade count, and drawdown. This gives a more granular view of where the strategy's edge comes from.

### Expected interpretation

For a long-only SMA-trend strategy on MES:

- **Trend + Low/Moderate Vol (Tier 1):** The "sweet spot" — the strategy should perform best here. This is where the SMA-trend signal is active and volatility is not disrupting fills.
- **Trend + High Vol (Tier 2):** The strategy should still perform, but with wider stops and potentially more whipsaw around the trend. The existing +HighVol block already captures part of this.
- **Range + Low/Moderate Vol (Tier 3):** The strategy should trade less (the trend filter is less active) and have lower edge. This is the "dead zone" for a trend strategy.
- **Range + High Vol (Tier 4):** The strategy should trade least and have the weakest edge. High volatility in a range market produces false breakout signals. The existing +Crisis+HighVol block already excludes this partially.

### Implementation note

This overlay is a **documentation and analysis enhancement**, not a change to the strategy's entry/exit rules. The strategy's tier-block selection (walk-forward-selected blocked set) remains the primary regime filter. The coarse trend/range overlay is an additional lens on the same backtest results — it does not require re-running the backtest, only re-partitioning the existing OOS windows by ADX state.

If the overlay is to be used as a live regime filter (e.g., to reduce position size in range markets), that would be a separate strategy enhancement and would require its own WFO validation. This document does not propose that — it only proposes the overlay as a regime-split reporting enhancement.

## Why this is an enhancement, not a gating fix

The JARVIS regime-split gate requires that the strategy's edge be demonstrated across multiple regimes. The current volatility-tier split already satisfies this:

- Edge persists across all 4 tier-block combos.
- The HighVol-only block (PF 1.666) is the strongest, demonstrating that the strategy works even in high-volatility conditions.
- The +Crisis+HighVol block (PF 1.479) is the weakest, but still above 1.0.

Adding a coarse trend/range overlay would:

- Provide a more granular view of regime performance.
- Help identify whether the strategy's edge is concentrated in trending regimes (as expected for a trend strategy) or spread across regimes.
- Strengthen the regime analysis for the paper-shadow promotion package.

But it is not gating. The volatility-tier split already passes the regime-split gate. This overlay is a "consider" item, closed by documentation, not by code change.

## Related

- Backtest critique: `docs/research/backtest-critique-mes_sma_trend_vix_pctile-2026-09-24.md` (open item 5)
- Strategy registry entry: `docs/research/strategy-registry/entries/mes_sma_trend_vix_pctile.json` (field `metrics.regime_split`)
- Verdict snapshot: `docs/research/mes-vix-pctile-rank1-verdict-snapshot-2026-09-18.json`
- Critique checklist: `docs/research/backtest-critique-checklist.md` (regime split gate)
- Macro regime context spec: `docs/research/macro-regime-context-spec.md`
