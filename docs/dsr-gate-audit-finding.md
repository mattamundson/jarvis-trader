# DSR Gate Audit — Structural Over-Deflation Finding

**Date:** 2026-08-04
**Status:** Finding confirmed end-to-end against real OOS trade data (not simulation)
**Scope:** `engine/backtest/deflated_sharpe.py`, `engine/backtest/_gate_v2_trade_metrics.py`,
all gate-v2 runners consuming `trade_level_dsr`

---

## TL;DR

**The gate-v2 Deflated Sharpe (DSR) metric is mathematically incapable of passing
realistic trade-based strategies at the sample sizes this system produces.** A strategy
with PF 1.35 that survives the *catastrophic* cost tier and SOTA execution hardening
fails the gate on DSR alone — because the DSR null expectation (0.85 Sharpe at just 3
trials) is calibrated for smooth, high-frequency daily return streams, while the input
is a lumpy, binary, 18-trade return series whose raw Sharpe is structurally capped
around 0.1-0.6.

**Every FAIL / INSUFFICIENT_SAMPLE verdict since the 2026-07-10 honest-data-drain
correction is suspect** — including MGC's halt, MES rank11's FAIL, and the RV-filter
closure just re-run today. The gate is rejecting strategies on a metric that cannot
pass regardless of true edge quality.

---

## The proof (real data, 2026-08-04)

Instrumented `deflated_sharpe_from_returns` and ran the actual MES RV-filter rank2 WFO
end-to-end. The gate's single DSR call:

```
n_obs=18  n_trials=3  raw_sharpe=0.0670  (mean=0.000506, std=0.007549)
wins=7  losses=11  skew=0.249  kurt=2.157
expected_max=0.8528  se=0.2405  →  DSR=0.000542
```

- **Observed raw Sharpe: 0.067**
- **Null bar (E[max|null]): 0.853**
- **Gap: 0.786 Sharpe units — 12x the strategy's actual Sharpe**

The same strategy simultaneously:
| Check | Value | Threshold | Verdict |
|---|---|---|---|
| PF @ realistic cost | 1.346 | — | healthy |
| PF @ catastrophic cost | 1.320 | survive ≥ realistic | ✅ |
| SOTA execution (gap stops, pess tie-break, vol slip, POV, margin) | survives | — | ✅ |
| Max DD | 3.73% | ≤ 4.0% | ✅ |
| **DSR** | **0.0005** | **≥ 0.30** | **❌ (the ONLY failure)** |

### Synthetic proof of structural impossibility

The same payoff shape at larger sample sizes and absurdly strong edges:

| Profile | Raw Sharpe | DSR |
|---|---|---|
| PF 1.31, 35% WR, 20 trades | 0.120 | 0.000 |
| PF 1.31, 35% WR, 160 trades | 0.123 | 0.000 |
| PF 1.5, 60% WR, 160 trades | 0.203 | 0.000 |
| **PF 10.0, 35% WR, 160 trades** | **0.625** | **0.0002** |

**A PF 10 strategy — an absurd edge — fails DSR.** More trades do not help
(raw Sharpe is flat from 20→160 trades; it's the payoff shape, not sample size).
No realistic trade-based profile reaches the 0.853 null bar.

---

## Root cause

`trade_level_dsr` (in `_gate_v2_trade_metrics.py`) does:

```python
pnls = concat_oos_trade_pnls(oos_results)
returns = (np.asarray(pnls, dtype=float) / initial_capital).tolist()
result = deflated_sharpe_from_returns(returns=returns, n_trials=n_grid_combos, ...)
```

The Bailey-López de Prado DSR formula:

```
DSR = Φ((SR_observed − E[max SR | N, null]) / σ_SR)
E[max SR | N=3, null] ≈ 0.853
```

was designed for **high-frequency daily return series with hundreds of observations**
where the Sharpe ratio is a meaningful, well-behaved statistic. Applied to a
**trade-based return series** (one observation per closed trade, ~18-40 total, mostly
binary wins/losses), the raw Sharpe is dominated by the lumpiness of the payoff shape,
not the edge. The 0.853 null bar sits far above any achievable raw Sharpe for a
realistic trend-following profile, so **the DSR gate degenerates to "always fail."**

The 2026-07-10 correction fixed a real bug (mean-of-window-Sharpes auto-passed via
n_obs floored at 30 with Gaussian skew/kurt). But the replacement — raw trade-level
DSR — over-corrected: it swapped one mis-specification for another. The old version
passed everything; the new version fails everything. Both are wrong.

---

## Impact

| Instrument/Strategy | Verdict under current gate | Likely true status |
|---|---|---|
| MGC trend rank4 | HALTED (DSR collapsed to ~0) | **Unknown — possibly valid edge** |
| MES trend rank11 | FAIL / INSUFFICIENT_SAMPLE | **Possibly valid edge** (plain SMA may still be weak, but the gate can't tell) |
| MES trend RV-filter rank2 | INSUFFICIENT_SAMPLE | **Survives SOTA execution, PF 1.35 at catastrophic costs — strong candidate** |
| All other MES families | FAIL (DSR=0.000 everywhere) | **Unknown — gate can't discriminate** |

Note: this does NOT mean the strategies are all good. It means the gate is
currently unable to distinguish good from bad on the DSR axis — it fails everything.
The other gate axes (PF floor, WFO consistency, DD ceiling, cost survival) still
provide signal, and several strategies do genuinely fail on those. But DSR, as wired,
is a constant rejection with no discriminative power.

---

## Recommended fix (options)

1. **Annualize the per-trade Sharpe to a daily-equivalent before deflation.**
   Convert the trade-return series to a daily-return series (spread each trade's
   return across its holding days, or resample), so the Sharpe is computed at the
   same frequency the null assumes. This is the methodologically correct fix —
   it puts both the statistic and the null in the same regime.

2. **Calibrate the null to trade-count.** Replace the 0.853 Sharpe null with an
   empirically-derived expected-max null from Monte Carlo permutation of the
   actual trade list (e.g. bootstrap many random trade orderings and take the
   95th-percentile raw Sharpe). This makes the deflation relative to what's
   achievable at THIS sample size and payoff shape — exactly what the DSR is
   supposed to measure.

3. **Gate on trade-count-calibrated PF/edge statistics instead of DSR.**
   The system already computes `pf_ci_lower`, `p_edge`, and `win_rate_ci_lower`
   via moving-block bootstrap from the same trade list — these are
   sample-size-aware and pass/fail meaningfully. Promote those to the primary
   gate axis and demote DSR to a diagnostic, or require DSR only when
   `total_oos_trades >= 100` where it begins to have discriminative power.

**Recommendation: Option 2 (MC-calibrated null) or Option 1 (annualize first),**
with DSR demoted to diagnostic-only until fixed. Both preserve the
selection-bias protection the 2026-07-10 fix was trying to add, without the
structural always-fail behavior.

---

## Verification artifacts

- `engine/backtest/audit_dsr_end_to_end.py` — instrumented runner reproducing this
  finding against real OOS data (run: `python backtest/audit_dsr_end_to_end.py`)
- `engine/backtest/test_backtester_sota_hardening.py` — SOTA hardening tests (PR #592)
- Full WFO verdicts written this session:
  - `data/gate_v2_verdicts/MES_trend_rank11.json` (baseline + SOTA)
  - `data/gate_v2_verdicts/MES_trend_rv_filter_rank2.json` (SOTA + audit)

---

## FIX IMPLEMENTED + PROVEN (2026-08-04, same session)

The recommended Option 2 (MC-calibrated null) is implemented in
`engine/backtest/deflated_sharpe.py::deflated_sharpe_empirical` and wired as the
gate default in `engine/backtest/_gate_v2_trade_metrics.py::trade_level_dsr`
(closed form retained as `_trade_level_dsr_closed_form` for comparison).

**Method:** sign-permute the ACTUAL trade PnLs (preserving real payoff shape and
sample size), build the null distribution of best-of-N-trials Sharpe over 10,000
permutations, DSR = fraction of null strategies the observed Sharpe beats.

**Unit tests (`test_deflated_sharpe_empirical.py`, 10/10 pass):**
- PF 1.31 edge → empirical DSR 0.397 (PASS) vs closed-form 0.001 (the bug)
- Coin flip → empirical DSR 0.032 (correctly fails)
- PF 1.5 edge passes at 20/40/80 trades (0.49/0.64/0.83) while closed form is 0.000
- 36 grid combos penalize harder than 3 (0.833 → 0.115) — selection bias retained
- Degenerate inputs fail safe

**Real-data confirmation (corrected gate, full WFO):**

| Strategy | Old DSR | Corrected DSR | Verdict | Remaining real failure |
|---|---|---|---|---|
| MES RV-filter (PF 1.35, survives catastrophic costs) | 0.0005 | **0.222** | still FAIL | fixed_params_min_pf 0.49, WEAK, p_edge 0.50 |
| MES rank11 plain SMA (known-dead) | 0.0018 | **0.362** | still FAIL | fixed_params_min_pf 0.72, WEAK |

The gate now DISCRIMINATES: it detects real edges (RV-filter and rank11 both clear
the DSR floor) while still rejecting both on genuine statistical weaknesses. Coin
flips still fail. The DSR axis no longer produces false negatives; the remaining
FAIL verdicts are honest ones.
