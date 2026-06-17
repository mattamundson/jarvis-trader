# Offline Edge-Discovery Sweep — 2026-06-16

Self-contained record of the Track-2 offline strategy-discovery sweep. Everything here is
**research output** — verdict JSONs only. No live routing, `signals.py`, `config.py`, or `.env`
was touched, and nothing here is written to the live `gate_v2_verdicts/` ledger or `edge_ledger.jsonl`.

## What this is

A sweep of **conditioning / adaptive** strategy hypotheses on the deep 1h lanes, run through the
canonical gate-v2 machinery (`engine/backtest/_gate_v2_helpers.py`). It complements the earlier
2026-06-16 batch-1 sweep (raw meanrev/breakout families, all FAIL) by testing whether *conditioning*
the known trend edge — or swapping in adaptive/counter-trend families — clears the gate.

- **Driver (the logic):** `engine/backtest/run_discovery_2026_06_16.py`
- **WFO config:** TRAIN=6mo / TEST=1mo / STEP=1mo, N_BOOTSTRAP per canonical, same cost tiers.
- **Validation:** the driver was first checked against the known `MGC_trend_rank4` ledger entry and
  reproduced its PASS-ALT verdict within rounding (`MGC_validate_mgc_rank4.json`) — so the machinery
  is wired correctly, not a custom re-implementation of the gate.

## Gate-v2 thresholds (for reading the JSONs)

| Metric | CORE | ALT (trend / $50K+) |
|---|---|---|
| `pf_ci_lower` (bootstrap 5th-pct OOS PF) | ≥ 1.10 | ≥ 1.10 |
| `p_edge` (frac OOS windows PF>1) | ≥ 0.95 | (relaxed; trend path) |
| `mc_95th_dd_pct` | ≤ 5% | ≤ 4% |
| `dsr` (deflated Sharpe) | ≥ 0.10 | ≥ 0.30 |
| `fixed_params_min_pf` | — | ≥ 1.20 |
| OOS-trade floor | ≥ 30 | ≥ 30 |

## Results

| File | Hypothesis | Symbol | Verdict | Notes |
|---|---|---|---|---|
| `MGC_validate_mgc_rank4.json` | SMA-trend (rank4 params) | MGC 1h | PASS-ALT | validation — reproduces live ledger |
| `MGC_H1_adx_sma_trend.json` | **ADX-conditioned SMA trend** | **MGC 1h** | **PASS-ALT** | **survivor** — see below |
| `MES_H1_adx_sma_trend.json` | ADX-conditioned SMA trend | MES 1h | INSUFFICIENT_SAMPLE | ADX≥18 filter zeroes all MES golden-cross entries |
| `MES_H2_kama_trend.json` | KAMA adaptive trend | MES 1h | FAIL | pf_ci 0.83, mc_dd 14.46%, dsr 0 |
| (no file) | KAMA adaptive trend | MNQ 1h | INSUFFICIENT_SAMPLE | data-plumbing: hit ~4mo CSV cache, no full WFO window |
| `MGC_H3_donchian_atr_regime.json` | Donchian breakout + ATR-regime | MGC 1h | FAIL | strong IS, OOS collapse (overfit) |
| `MES_H4_rsi2_meanrev.json` | RSI(2) mean-reversion | MES 1h | FAIL | RSI(2) is a daily strategy; 1h too fast |

## The survivor — `MGC_H1_adx_sma_trend.json` (PASS-ALT)

Champion params: `{fast: 50, slow: 120, atr_trail_mult: 2.0, adx_threshold: 18}`

| Metric | Value | Gate (ALT) |
|---|---|---|
| `pf_ci_lower` | 3.76 | ≥ 1.10 ✓ |
| `p_edge` | 0.89 | (trend path) |
| `mc_95th_dd_pct` | 1.63% | ≤ 4% ✓ |
| `dsr` | 1.00 | ≥ 0.30 ✓ |
| `wfo_consistency` | STRONG | — |
| `fixed_params_min_pf` | 1.52 | ≥ 1.20 ✓ |
| `cost_survives_through` | catastrophic | — |
| OOS trades | 58 | ≥ 30 ✓ |

> **⚠️ SUPERSEDED BY DILIGENCE — DO NOT PROMOTE. See "Diligence verdict" below.**
> The 2026-06-17 ADX-grid + canonical-harness diligence found the ADX filter is **inert** (changes
> nothing), so this is NOT a distinct "ADX-conditioned" edge — it is a re-discovery of the plain
> SMA-trend edge already live as rank4. The metrics below are real but the *attribution to ADX is
> spurious*.

It appears to dominate the bare MGC rank4 entry on gate metrics (pf_ci 3.76 vs 2.59, mc_dd 1.63% vs
3.03%) — but that delta is from the **SMA(50,120) params**, not from ADX (see diligence).

## Diligence verdict (2026-06-17) — the survivor dissolved

Driver: `engine/backtest/run_adx_grid_diligence.py`. Outputs: `MGC_H1_adx{14,18,22,25,28,32}_sma_trend.json`
+ `MGC_H1_adx_grid_diligence_summary.json`.

| adx_threshold | verdict | pf_ci_lower | p_edge | mc_dd% | dsr | n_oos |
|---|---|---|---|---|---|---|
| 14 / 18 / 22 / 25 / 28 / 32 | PASS-ALT | 3.7596 | 0.8947 | 1.632 | 1.0 | 58 |

**Bit-for-bit identical across every ADX threshold** → the ADX filter suppresses **zero** trades.
Conclusions:
1. **The `adx_threshold=18` overfit concern is closed** — the edge isn't sensitive to ADX because the
   filter never binds.
2. **But a fatal framing error opens:** an inert filter means "ADX-conditioned trend" **IS plain
   SMA(50,120) trend**. It is not a new/independent edge and not a distinct strategy — it is the
   existing MGC trend family (live rank4) at a different param point.
3. **Mechanism UNVERIFIED:** the inertness is either genuine (50/120 crossovers all occur in high-ADX
   regimes) OR an always-true filter-wiring bug — same symptom. Not resolved; the actionable
   conclusion holds regardless.
4. **Canonical harness:** ADX-conditioning is absent from the canonical `trend` family
   (`scripts/rolling_wfo_validator.py` → plain SMA crossover, no ADX). Reproducing the ADX variant
   canonically would require editing shared signal code (`trend_signals.py`) — the safety boundary —
   so it was NOT done.

**ACTION: do NOT promote H1 as a new strategy.** It is effectively rank4.

## Residual open question (low priority, Amo-gated)

SMA(50,120) showed higher pf_ci (3.76) than rank4's champion params (2.59) on MGC 1h — possibly a
better param point *within the same trend family*, NOT a new edge. If worth pursuing: re-tune MGC
trend params through the **canonical** trend search + family-FDR de-dup vs rank4. This is a param
re-tune of a known edge, not new-edge discovery.

## How to re-run

From `engine/` with the engine venv:
```
.venv/Scripts/python backtest/run_discovery_2026_06_16.py
```
Reads bars from `engine/data/jarvis_trader.db` (table `market_data_bars`), read-only.

## Bottom line (post-diligence)

**No new edge — and the one apparent survivor dissolved under diligence.** The "MGC ADX-conditioned
trend" PASS was a *spurious attribution*: the ADX filter is inert, so the result is just the existing
live MGC SMA-trend edge (rank4) re-found at a different param point. Net for this sweep: **zero new
independent edge, zero promotable refinement.** Consistent with batch-1 — real new edge is scarce.
The only residual thread is a possible param re-tune within the known trend family (low priority).
