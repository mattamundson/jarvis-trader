# Term-Structure Overlay A/B -- MES (decision gate)

_Generated: 2026-06-22T08:35:23.498733+00:00_

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

### Scope & caveats

- **MES only.** MES is the one symbol with a VIX-aware champion WFO runner (`run_mes_trend_vix_rank1.py`) and the flagship equity-index symbol where an equity-vol term-structure signal is most applicable. MNQ has caches but no VIX champion runner; MCL/MGC are commodities with a weaker prior. Extending the gate to those requires building a per-symbol VIX champion first -- a separate task.
- **New hypothesis, not a validated port.** The term-structure filter is validated for *short-vol* strategies (~/Code/options-vrp); its value on directional micro-futures is exactly what this gate tests.
- Arm A native uses the VIX-grid deflation (n=9); rebuilt arms use the overlay-sweep deflation (n=8). ALT-path fixed-params/cost inputs are baseline (no overlay) and shared by both arms -- the overlay acts on the CORE per-window stream. DD is rebuilt at trade granularity (identical method both arms). Fractional multipliers model aggregate sizing; the live overlay clamps to integer contracts (coarser at 1-2 lots).