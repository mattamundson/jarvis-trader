# RV-filter A/B — does the realized-vol regime filter rescue the intraday trend near-miss?

**Verdict: NO. Honest negative — hypothesis refuted.** The realized-volatility
filter (`min_rv_annualized` ∈ {9, 12}, interval-correct annualization) does not
convert any intraday trend near-miss to a gate-v2 PASS, and on the prime target
(MGC 5m) it actively *destroys* the edge while leaving the drawdown wall intact.

## A/B table (baseline no-filter vs RV-filtered, same trend grid)

| spec | trades | PF_lo | p_edge | DSR | mc_95th_dd% | WFO | verdict |
|---|---|---|---|---|---|---|---|
| MGC sma_trend **5m** BASE | 388 | **1.254** | **0.833** | **0.792** | 5.77 | STRONG | FAIL (near-miss) |
| MGC sma_trend_rv **5m** RVF | 302 | 1.001 | 0.583 | 0.000 | 5.69 | MODERATE | FAIL |
| MGC sma_trend **15m** BASE | 293 | 1.116 | 0.583 | 0.000 | 5.37 | MODERATE | FAIL |
| MGC sma_trend_rv **15m** RVF | 178 | 0.991 | 0.583 | 0.000 | 5.17 | MODERATE | FAIL |
| MES sma_trend **5m** BASE | 200 | 0.574 | 0.500 | 0.000 | 5.57 | WEAK | FAIL |
| MES sma_trend_rv **5m** RVF | 266 | 0.885 | 0.600 | 0.000 | 5.66 | MODERATE | FAIL |
| MES sma_trend **15m** BASE | 409 | 0.728 | 0.500 | 0.000 | 5.61 | WEAK | FAIL |
| MES sma_trend_rv **15m** RVF | 234 | 0.666 | 0.389 | 0.000 | 5.42 | WEAK | FAIL |

## What the filter actually did

1. **It killed the one real edge.** MGC 5m was the strongest tradeable near-miss
   (DSR 0.79, PF lower-bound 1.25). Adding the vol gate collapsed it to DSR 0.00 /
   PF_lo 1.00 — i.e. *no* edge. Gold's intraday trend lives in **moderate** vol,
   not just high vol; filtering out the lower-vol bars removed positive-expectancy
   trades. This matches the original runner's own caveat: the 9% threshold is
   MES-derived and "MGC calibration is pending 60+ live trades."

2. **It barely moved the drawdown wall.** Every spec stays at ~5.2–5.7% — above the
   5% core / 4% ALT ceiling. The largest improvement was MGC 15m (5.37→5.17%),
   nowhere near 4%. **The ~5.5% drawdown is structural to intraday SMA-crossover
   trend, not a low-vol false-signal artifact** the filter can remove.

3. **The two genuine no-edge specs (MES) stayed no-edge.** MES 5m PF rose
   0.57→0.89 but never crossed 1.0; the filter cannot manufacture an edge that the
   base strategy lacks.

## Conclusion & implication

The realized-vol regime filter is the wrong lever for this drawdown wall. Two
things are now established by direct test, not assumption:

- The intraday trend **edge** (where it exists, MGC) is real but **fragile to
  vol-gating** — do not apply a high-vol filter to gold trend.
- The intraday trend **drawdown** is structural. Lowering it needs a mechanism
  that caps *position-level* loss (tighter ATR trail, a hard intraday stop, or
  volatility-scaled sizing), **not** a regime entry-filter that just trades less.

**Next lever (not run here):** re-test the MGC 5m near-miss with the drawdown
attacked directly — tighter `atr_trail_mult` and/or a per-trade hard-stop /
vol-scaled sizing grid — to see whether mc_95th_dd drops below 4% *without*
sacrificing the DSR 0.79 / PF_lo 1.25 that the RV filter destroyed. That keeps
the proven edge and targets the actual failing metric.

_Research only. All verdicts written to data/discovery_factory/ (never
gate_v2_verdicts/); promotion remains a human decision._
