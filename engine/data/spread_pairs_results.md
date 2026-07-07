# Relative-Value Spread Scan — Does the Class Generalize Beyond ES-NQ?

**Date:** 2026-06-24
**Module:** `engine/backtest/spread_pairs_scan.py` (reuses `spread_backtest` pure math; 6 tests)
**Question:** ES-NQ showed a non-stationary edge. Is relative-value a viable strategy *class*, or was ES-NQ a one-off?

Same pipeline as ES-NQ (log-spread z-score, no-look-ahead, rolling-OOS WFO, pooled bootstrap, **mandatory chronological H1/H2 split**), FIXED a-priori params (window 40 / entry 2.0 / exit 0.5 / stop 4.0), 1h bars.

## Results (cost = 2 bp/leg)

| Pair | OOS | pf_ci_lo | p_edge | H1 pf / sum | H2 pf / sum | Verdict |
|---|---|---|---|---|---|---|
| **MES-M2K** (S&P vs Russell) | 264 | **2.26** | 1.00 | 1.25 / +0.087 | 5.61 / +1.213 | **CANDIDATE** |
| MNQ-M2K (Nasdaq vs Russell) | 251 | 1.18 | 0.99 | 1.00 / −0.001 | 2.57 / +0.460 | NON-STATIONARY |
| ZN-ZB (10Y vs 30Y, "NOB") | 131 | 1.66 | 1.00 | 1.21 / +0.010 | 5.44 / +0.093 | CANDIDATE* |
| ES-NQ (prior) | 256 | 2.45 | 1.00 | 0.91 / **−0.022** | 7.96 / +0.902 | NON-STATIONARY |

## Verdict: relative-value partially generalizes; **MES-M2K is the strongest candidate found**

**MES-M2K is the best relative-value pair tested — materially better than ES-NQ:**
- Per-window WFO: 0.87, **1.28, 1.69, 1.60, 1.80, 6.37**, 1289.6 — **6 of 7 windows win**, and the
  edge is present in the *middle* of the sample (1.69/1.60/1.80), not only the tail. ES-NQ by
  contrast *lost* its first two windows and made everything in 2025-H2.
- **H1 is genuinely profitable** (PF 1.25, +0.087) — it clears the chronological-split check that
  ES-NQ failed.
- **Cost-robust:** still a CANDIDATE at 4 bp/leg (pf_ci_lo 2.08); only degrades to NON-STATIONARY
  at a punitive 6 bp. (The last window's PF 1289 is a degenerate near-zero-loser artifact and is
  *not* what carries the result — the mid-sample 1.3–1.8 windows do.)

**The others are not real:**
- **MNQ-M2K**: H1 flat (−0.001), all profit back-loaded; fails at 4 bp (pf_ci_lo 1.07). Same trap as ES-NQ.
- **ZN-ZB** (*): passes the binary split but only 12 months / 3 windows, H1 barely positive (+0.010),
  and **fails at 4 bp** (pf_ci_lo 1.09 / NO_EDGE). Too thin + cost-fragile to trust.

## The load-bearing caveat (shared regime)

Every equity-index pair **loses the first window (2024-07→2024-10)** and strengthens through 2025
(ES-NQ 0.38, MES-M2K 0.87, MNQ-M2K 0.62 in that window). So index-spread mean-reversion was *weak
in 2024-H2 and strong in 2025* across the board — a broad regime tilt, not a per-pair structural
inefficiency. The pairs peak in *different* months (ES-NQ 2025-07/10, MES-M2K 2025-10/2026-01,
MNQ-M2K 2026-01), which argues against one single lucky window but **for** a 2025-favorable regime.

So even MES-M2K — the cleanest of the set — is partly fitting the favorable post-2024 regime.
Persistence cannot be settled on 26 months / 7 windows. The honest resolution is the same as
ES-NQ: **forward out-of-sample time.**

## Action

MES-M2K is added to the dark forward paper track (`spread_paper_track.py`) alongside ES-NQ, so we
accumulate a clean OOS record on the *better* candidate. Evaluate with
`python -m backtest.spread_paper_track --report`.

Reproduce: `python -m backtest.spread_pairs_scan` (and `--cost-bps 4.0`).
