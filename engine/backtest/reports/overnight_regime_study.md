# MES Overnight Carry — Regime-Conditional Variant (DOCUMENTED NEGATIVE)

Follow-up to the rank1 overnight study, which was a **near-miss FAIL**
(`pf_ci_lower 0.9955` vs 1.10): raw overnight equity carry has a real edge most
of the time but lost OOS consistency on the 2024 equity bear cluster. The
hypothesis (both 2026-06-17 research streams) was that the overnight premium
concentrates in calm/uptrend regimes, so a **volatility-stress gate** that
stands aside when trailing realized vol is elevated should drop the selloff
sessions and recover consistency.

## What was tested

`run_mes_overnight_regime_rank1.py` — same gate-v2 WFO battery as rank1
(Train 6mo / Test 2mo / Step 1mo, 20 windows), with a **2D grid**:

- `filter_len ∈ [0, 200]` — SMA trend filter (`close > SMA`)
- `max_rv_ann ∈ [0, 15, 20, 30]` — skip entry when 20-bar annualized realized
  vol (%) exceeds the threshold (`0` = off). Price-only proxy for "VIX contango
  / low-stress."

8 combos; `(0, 0.0)` reproduces raw overnight carry so the grid can only help or
no-op relative to rank1. The larger grid intentionally raises the DSR bar.

## Verdict: FAIL (documented negative)

| Metric | Regime variant | Raw rank1 | Gate |
|--------|----------------|-----------|------|
| `pf_ci_lower` | **0.989** | 0.9955 | ≥ 1.10 |
| `p_edge` | 0.579 | 0.60 | ≥ 0.95 |
| `dsr` | **0.000** | 0.0 | ≥ 0.10 |
| `mc_95th_dd` | **11.59%** | 20.1% | ≤ 5% (≤4% alt) |
| `rolling_wfo` | MODERATE | — | MODERATE/STRONG |
| `cost_survives` | catastrophic | — | ≥ realistic |
| `fixed_params_min_pf` | 1.022 | — | ≥ 1.20 |
| OOS trades | 373 | 588 | ≥ 30 |

Champion combo: `filter_len=0, max_rv=15` (pure vol gate, no trend filter).

## Interpretation

- **The vol-stress gate works as designed on drawdown** — it nearly halved the
  Monte-Carlo 95th-percentile drawdown (20.1% → 11.6%) by removing high-vol
  selloff sessions. That part of the hypothesis held.
- **But it did NOT restore edge consistency.** `pf_ci_lower` stayed ~0.99 and
  `p_edge` ~0.58 — the 2024 bear cluster is not cleanly separable by a realized-
  vol threshold; the gate removes good sessions along with bad ones, and several
  high-`max_rv` windows OOS-starved to 0–2 trades.
- **`dsr = 0.000` is the stop signal.** With 8 combos and inconsistent OOS, the
  deflated-Sharpe selection-bias penalty zeroes out. Adding *more* regime axes
  would make DSR worse, not better — continuing to grid variants here is
  p-hacking, not edge discovery.

## Conclusion

The **regime-conditional overnight lead is closed as a documented negative.**
Vol-gating is a useful *risk* lever (drawdown −42%) but is not, on its own, an
edge-consistency fix for overnight MES carry. This mirrors the broader
finding that MES needs a genuinely different return source, not a filter on a
marginally-positive one. The `max_rv_annualized` gate added to
`overnight_signals.py` is retained (backward-compatible, default off) as reusable
machinery. VALIDATION ONLY — no live routing.
