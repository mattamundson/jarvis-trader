# Gate v2 Metric-Integrity Fix — Re-Gate Result (2026-05-30)

Branch: `fix/gate-v2-metric-integrity` (worktree). Paper-only system
(`LIVE_TRADING_ENABLED=False`); no live config touched, no engine restart, no push.
Canonical verdicts in the main checkout are UNMODIFIED — this re-gate wrote only to the
worktree copies.

> **All numbers below are from actual runs** of `run_mes_trend_rank11.py` and
> `run_mgc_trend_rank4.py` in the worktree (engine `.env` loaded, real bar caches). An
> earlier draft of this file contained estimated/placeholder figures from the
> `gate-v2-independent-recompute` workflow; those were wrong and have been replaced with the
> executed results.

## What changed

The two live-book gate runners computed `mc_95th_dd` and `dsr` from **window-level**
aggregates (one drawdown per WFO window; a Sharpe = mean of per-window Sharpes). Both are
mis-specified for sparse strategies. Fix: a new centralized, tested helper
`engine/backtest/_gate_v2_trade_metrics.py` computes both from the **actual concatenated
OOS trade list**, reusing the canonical primitives (`monte_carlo.bootstrap_max_dd`,
`deflated_sharpe.deflated_sharpe_from_returns`) that `scripts/validate_strategy.py` already
uses. The legacy window-level DD is retained in the verdict JSON as
`mc_95th_dd_window_legacy` for transparency only — it is NOT used for the decision.

Tests: `engine/tests/test_gate_v2_trade_metrics.py` (10/10), incl. a regression test proving
trade-level DD surfaces a cross-window losing streak that window-level p95 reports as 0.5%.
Existing `test_gate_v2_dual_pathway.py` still passes (16/16). Total 26/26.

## Before / after — MES (run_mes_trend_rank11, 16 OOS trades / 12 windows-with-trades)

| Metric | Gate window-level (legacy) | Re-gate trade-level (correct) | ALT bar | Clears? |
|---|---|---|---|---|
| mc_95th_dd | 0.82% | **1.78%** | <= 4.0% | **yes** |
| dsr | 1.0 | 1.0 (≈0.999996) | >= 0.30 | yes |
| p_edge (core only) | 0.75 | 0.75 | >= 0.95 | no (core) |
| wfo / fixed_min_pf / cost | STRONG / 1.35 / catastrophic | STRONG / 1.35 / catastrophic | — | yes |

**MES verdict: PASS-via-ALT → PASS-via-ALT (UNCHANGED).** Trade-level DD is ~2.2x the
window-level figure but still well under the 4% ALT ceiling. The strategy's live
authorization survives correct metrics.

## Before / after — MGC (run_mgc_trend_rank4, 67 OOS trades / 19 windows)

| Metric | Gate window-level (legacy) | Re-gate trade-level (correct) | ALT bar | Clears? |
|---|---|---|---|---|
| mc_95th_dd | 1.24% | **3.03%** | <= 4.0% | **yes** |
| dsr | 1.0 | 1.0 | >= 0.30 | yes |
| p_edge (core only) | 0.68 | 0.68 | >= 0.95 | no (core) |
| wfo / fixed_min_pf / cost | MODERATE / 1.36 / catastrophic | MODERATE / 1.36 / catastrophic | — | yes |

**MGC verdict: PASS-via-ALT → PASS-via-ALT (UNCHANGED).** Trade-level DD ~2.4x the
window-level figure, still under 4%.

## Bottom line — the earlier "MES flips to NO_TRADE" thesis is REFUTED

| Strategy | Canonical | Re-gate (correct trade-level metrics) | DD: window → trade |
|---|---|---|---|
| MES | PASS via ALT | **PASS via ALT (unchanged)** | 0.82% → 1.78% |
| MGC | PASS via ALT | **PASS via ALT (unchanged)** | 1.24% → 3.03% |

The window-level DD metric **was** mis-specified and **did** understate tail drawdown (~2.2–2.4x),
confirming the integrity concern was real and worth fixing. **But the correction does NOT flip
either live verdict.** The `gate-v2-independent-recompute` workflow's estimate (MES ~5.4% trade-level
DD → NO_TRADE) was substantially too aggressive: its hand-rolled sign-shuffle bootstrap diverged from
the codebase's canonical `bootstrap_max_dd` permutation MC, which yields 1.78%. This is exactly why
the fix had to be *run*, not inferred from the recompute.

## Key finding about DSR

The DSR stayed **1.0 for both strategies even after switching to real per-trade returns** with
correct skew/kurt. The metric-audit's "DSR is the load-bearing defect" alarm was overstated — the
DSR value did not change. The `deflated_sharpe.py:126-127` degenerate-variance fallback is a latent
defensive concern but is confirmed NOT to fire for these verdicts.

## Net assessment

The metric mis-specification is **real and now fixed** (trade-level MC + Deflated-Sharpe-from-returns,
centralized and tested). Both live paper strategies **remain correctly authorized** under the corrected
math — no live action required. The fix makes future verdicts (incl. the ATR-MES candidate) trustworthy.

## Remaining work (separate, gated — none blocking)

1. Deterministic fixed-list cost re-pricing (`cost_sensitivity_sweep.py`) — the cost sweep is still
   non-monotone (re-runs signals per tier); it did not affect these PASS verdicts but should be made
   deterministic for correctness.
2. Optional defensive hardening of `deflated_sharpe.py:126-127` (degenerate-variance → fail-conservative
   0.0) — latent, not flip-determinative here.
3. Propagate the trade-level helper to the other window-level runners (mcl_htf, mnq_breakout, m2k,
   wfo_lifecycle) for consistency.
