# Term-Structure Overlay A/B -- MES (decision gate)

_Generated: 2026-06-22T08:51:10.525579+00:00_

## RECOMMENDATION: **KILL**

`TS_OVERLAY_ENABLED` stays `False`. Enabling + the engine restart are Amo-only.

### Decision conditions (all four must hold to ENABLE)

| Condition | Result |
|---|---|
| Arm B clears gate v2 | False |
| dsr(B) > dsr(A) | False |
| maxDD(B) < maxDD(A) | False |
| mc_95th_dd(B) <= (A) | True |

### Gate v2 side-by-side

| Metric | Arm A (native) | Arm A (rebuilt) | Arm B (best) | Threshold |
|---|---|---|---|---|
| verdict | FAIL | FAIL | FAIL | PASS |
| pf_ci_lower | 0.5999 | 0.5999 | 0.4413 | >=1.10 |
| p_edge | 0.3571 | 0.3571 | 0.3077 | >=0.95 |
| mc_95th_dd | 0.9479% | 0.9336% | 0.9336% | <=5% (ALT 4%) |
| dsr | 0.0 | 0.0 | 0.0 | >=0.10 (ALT 0.30) |
| total OOS trades | 16 | 16 | 15 | -- |

### Best Arm B params

- flat_band: **0.0 pts**
- backwardation_mult: **0.0**
- standaside_on_backwardation: **True**
- contango_mult: 1.0, flat_mult: 1.0

### Full Arm B sweep

| flat_band | bwd_mult | standaside | verdict | pf_ci_lower | p_edge | mc_dd | dsr | trades |
|---|---|---|---|---|---|---|---|---|
| 0.0 | 0.0 | True | FAIL | 0.4413 | 0.3077 | 0.934% | 0.0 | 15 |
| 0.0 | 0.5 | False | FAIL | 0.5999 | 0.3571 | 0.934% | 0.0 | 16 |
| 0.5 | 0.0 | True | FAIL | 0.5999 | 0.3571 | 0.934% | 0.0 | 16 |
| 0.5 | 0.5 | False | FAIL | 0.5999 | 0.3571 | 0.934% | 0.0 | 16 |
| 1.0 | 0.0 | True | FAIL | 0.5999 | 0.3571 | 0.934% | 0.0 | 16 |
| 1.0 | 0.5 | False | FAIL | 0.5999 | 0.3571 | 0.934% | 0.0 | 16 |
| 2.0 | 0.0 | True | FAIL | 0.5999 | 0.3571 | 0.934% | 0.0 | 16 |
| 2.0 | 0.5 | False | FAIL | 0.5999 | 0.3571 | 0.934% | 0.0 | 16 |

### Powered full-sample A/B (in-sample diagnostic)

Higher-N readout than the trade-starved WFO: the champion VIX combo `{'vix_min': 12, 'vix_max': 28}` over the full dataset = **32 trades**.

**Regime breakdown:** CONTANGO 30 / FLAT 2 / BACKWARDATION 0 / NO_DATA 0. _Any combo improves (Sharpe up AND maxDD not worse): **False**._

| Arm | flat_band | bwd_mult | PF | Sharpe | maxDD | pnl | trades |
|---|---|---|---|---|---|---|---|
| A (OFF) | -- | -- | 1.5292 | 2.8383 | 3.886% | $2,877 | 32 |
| B | 0.0 | 0.0 | 1.3762 | 2.1273 | 3.946% | $2,045 | 31 |
| B | 0.0 | 0.5 | 1.4527 | 2.5007 | 3.916% | $2,461 | 32 |
| B | 0.5 | 0.0 | 1.5292 | 2.8383 | 3.886% | $2,877 | 32 |
| B | 0.5 | 0.5 | 1.5292 | 2.8383 | 3.886% | $2,877 | 32 |
| B | 1.0 | 0.0 | 1.5292 | 2.8383 | 3.886% | $2,877 | 32 |
| B | 1.0 | 0.5 | 1.5292 | 2.8383 | 3.886% | $2,877 | 32 |
| B | 2.0 | 0.0 | 1.5292 | 2.8383 | 3.886% | $2,877 | 32 |
| B | 2.0 | 0.5 | 1.5292 | 2.8383 | 3.886% | $2,877 | 32 |

_IN-SAMPLE diagnostic (no walk-forward / no DSR / not a gate verdict). Champion VIX combo over the full dataset for a higher-N readout than the trade-starved WFO. If few trades land in BACKWARDATION the overlay cannot help by construction._

### Scope & caveats

- **MES only.** MES is the one symbol with a VIX-aware champion WFO runner (`run_mes_trend_vix_rank1.py`) and the flagship equity-index symbol where an equity-vol term-structure signal is most applicable. MNQ has caches but no VIX champion runner; MCL/MGC are commodities with a weaker prior. Extending the gate to those requires building a per-symbol VIX champion first -- a separate task.
- **New hypothesis, not a validated port.** The term-structure filter is validated for *short-vol* strategies (~/Code/options-vrp); its value on directional micro-futures is exactly what this gate tests.
- Arm A native uses the VIX-grid deflation (n=9); rebuilt arms use the overlay-sweep deflation (n=8). ALT-path fixed-params/cost inputs are baseline (no overlay) and shared by both arms -- the overlay acts on the CORE per-window stream. DD is rebuilt at trade granularity (identical method both arms). Fractional multipliers model aggregate sizing; the live overlay clamps to integer contracts (coarser at 1-2 lots).