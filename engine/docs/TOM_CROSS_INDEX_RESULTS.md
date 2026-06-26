# Cross-index turn-of-month robustness — results

**Date:** 2026-06-24 · **Module:** `backtest/tom_cross_index.py` · **Data:** yfinance daily, max
history, beta-sized to a 5% DD budget, net@2bps.

## Why this was run

The beta-harvest gate variant (`BETA_HARVEST_GATE_PROPOSAL.md`) lowers the canonical p_edge
floor (0.95 → 0.60) in exactly the way that unblocks turn-of-month on SPY. Approving a gate
change that precisely rescues the one candidate, on a single instrument, warrants an independent
check first: **is TOM a broad equity month-turn effect, or an SPY-specific artifact?**
Pre-registered rule (written before running): an index corroborates if its beta-sized net TOM
series is chronologically stationary (H1 & H2 PF > 1) AND clears `pf_ci_lower ≥ 1.10` AND the
canonical `compute_gate_v2` fails the core on *exactly* p_edge (or passes). TOM is corroborated
overall at **≥ 4 of 6**.

## Result: NOT-CORROBORATED (3 / 6)

| sym | label | n | Sharpe net | pf_ci | p_edge | H1 PF | H2 PF | stationary | canon | beta-harvest | corroborates |
|-----|-------|---|-----------|-------|--------|-------|-------|------------|-------|--------------|--------------|
| SPY | large cap | 1604 | 0.79 | 1.17 | 0.618 | 1.17 | 1.14 | Y | FAIL | PASS | **yes** |
| QQQ | tech (NDX-100) | 1312 | 0.77 | 1.13 | 0.679 | 1.16 | 1.14 | Y | FAIL | PASS | **yes** |
| MDY | mid cap (S&P 400) | 1496 | 0.66 | 1.16 | 0.625 | 1.20 | 1.05 | Y | FAIL | PASS | **yes** |
| IWM | small cap (R2000) | 1254 | 0.22 | 1.01 | 0.593 | 1.11 | 0.96 | n | FAIL | FAIL | no |
| DIA | blue-chip (Dow 30) | 1368 | 0.52 | 1.08 | 0.586 | 1.12 | 1.06 | Y | FAIL | FAIL | no |
| EFA | intl developed (EAFE) | 1196 | 0.47 | 1.05 | 0.538 | 1.20 | 0.95 | n | FAIL | FAIL | no |

## Honest read

- **TOM is not an SPY artifact.** It reproduces with the same signature (stationary, pf_ci ≥ 1.10,
  fails canonical only on the mis-calibrated p_edge) in **QQQ and MDY** — independent of SPY.
- **But it does not robustly generalize across the full equity complex.** Small cap (IWM) and
  international developed (EFA) **lose chronological stationarity** (second-half PF < 1); the Dow
  (DIA) misses the pf_ci floor (1.08 < 1.10). Three of six fail the pre-registered bar.
- **Concentration pattern (hypothesis, post-hoc — not corroboration):** the effect is strongest in
  the most-indexed US large/tech/mid-cap names (SPY/QQQ/MDY) and weak/absent in small-cap and
  international. That is *consistent* with a month-end index-fund / 401k-rebalance flow story
  concentrating in the heavily-indexed names — but this narrative was formed after seeing the
  result and is not evidence.

## What this changes

1. **Do not lower the gate on a "broad robust effect" argument.** By the pre-registered criterion
   the breadth case did not clear (3/6 < 4/6). The beta-harvest variant may still be the right
   recalibration on its *statistical* merits (p_edge ≥ 0.95 over annual windows is structurally
   unmeetable for a long-beta harvest), but it should be decided on that argument alone — NOT on a
   claim that TOM is broadly corroborated, because it isn't.
2. **The forward paper-shadow becomes the decisive arbiter, not backtest breadth.** Since the
   cross-index breadth check is a caution, TOM's promotion case must rest on the ~6-month forward
   record (`tom_paper_track`) holding up out-of-sample — exactly the unavoidable clock. Start it now.
3. **The deployable instrument (MES = S&P 500) sits in the cluster that DID corroborate** (SPY large
   cap). That is reassuring for MES specifically, but does not rescue the *overall* breadth verdict —
   and noting it as a reason to proceed would be the goalpost-move this check exists to prevent.

## Reproduce

```
python -m backtest.tom_cross_index            # all 6 (fetches + caches missing)
python -m backtest.tom_cross_index --symbols SPY QQQ IWM
```
Tests: `pytest tests/test_tom_cross_index.py` (registry, verdict shape, ≥4/6 logic; fetch mocked).
