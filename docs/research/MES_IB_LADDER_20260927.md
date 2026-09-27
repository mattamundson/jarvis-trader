# MES Initial-Balance Ladder — Research Verdict

**Verdict: REJECT** · Analysis only · MES only · no runtime/risk changes.

- Input: `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\backtest\cache\MES_2024-09-22_2026-05-29_5m_cont.csv` · **119,096 rows** · `2024-09-22T22:00:00+00:00` → `2026-05-29T20:55:00+00:00` · SHA-256 `516beb11568f3270e595035b1dada669654c6b337f87b81b35fc386dff092a12`.
- Complete 5-minute sessions: **417**; IS/OOS: **250/167**.
- IS-selected configuration: `stop_entry__opposite_ib__full_ib__slip1`.
- OOS trades: **162**; PF **0.81187**; expectancy **$-11.913827**; CAGR **-27.649555%**; max DD **24.690722%**; observed-frequency Sharpe **-1.330078**.
- Campaign-deflated empirical DSR: **0.0** at **226** measured lower-bound trials.
- +1 tick/side stress expectancy: **$-14.413827**.
- Simple IB-break benchmark expectancy: **$-9.228642**.
- MFE mean/median: **20.371914 / 15.25 points**; MAE mean/median: **21.455247 / 18.125 points**; mean time-to-exit **202.469136 minutes**.
- Ledger reconciliation residual: **$0.0**.
- Disjoint halves: `{'h1_pf': 0.644624, 'h2_pf': 0.985589, 'h1_expectancy': -22.932346, 'h2_expectancy': -0.895309, 'both_positive': False}`.

## Descriptive ladder

```json
{
  "sessions": 417,
  "ambiguous_first_break_sessions": 0,
  "sessions_with_ib_break": 409,
  "ib_break_rate": 0.9808153477218226,
  "long_first_breaks": 220,
  "short_first_breaks": 189,
  "overnight_target_eligible": 215,
  "overnight_hit_rate_conditional": 0.6,
  "half_extension_hit_rate_given_break": 0.589242053789731,
  "full_extension_hit_rate_given_half": 0.5145228215767634
}
```

## All OOS variants — baseline cost

| configuration | trades | PF | expectancy ($) | CAGR (%) | observed-frequency Sharpe |
|---|---:|---:|---:|---:|---:|
| `close_confirm__ib_mid__full_ib__slip1` | 161 | 0.913462 | -4.304317 | -10.272632 | -0.587413 |
| `close_confirm__ib_mid__half_ib__slip1` | 161 | 0.83659 | -6.784907 | -16.019943 | -1.16638 |
| `close_confirm__ib_mid__ladder__slip1` | 161 | 0.913484 | -8.681118 | -20.32593 | -0.561558 |
| `close_confirm__ib_mid__overnight__slip1` | 76 | 1.144977 | 5.101382 | 5.909033 | 0.52603 |
| `close_confirm__opposite_ib__full_ib__slip1` | 161 | 0.880884 | -6.777143 | -16.002155 | -0.790983 |
| `close_confirm__opposite_ib__half_ib__slip1` | 161 | 0.790014 | -9.960373 | -23.187416 | -1.419597 |
| `close_confirm__opposite_ib__ladder__slip1` | 161 | 0.845568 | -18.277391 | -40.904515 | -0.989587 |
| `close_confirm__opposite_ib__overnight__slip1` | 76 | 0.927015 | -3.262105 | -3.71813 | -0.289852 |
| `stop_entry__ib_mid__full_ib__slip1` | 162 | 0.793344 | -10.883735 | -25.379642 | -1.516978 |
| `stop_entry__ib_mid__half_ib__slip1` | 162 | 0.793374 | -9.726327 | -22.801101 | -1.60664 |
| `stop_entry__ib_mid__ladder__slip1` | 162 | 0.795448 | -23.35429 | -51.201051 | -1.475661 |
| `stop_entry__ib_mid__overnight__slip1` | 82 | 0.866758 | -5.421524 | -6.633286 | -0.606175 |
| `stop_entry__opposite_ib__full_ib__slip1` | 162 | 0.81187 | -11.913827 | -27.649555 | -1.330078 |
| `stop_entry__opposite_ib__half_ib__slip1` | 162 | 0.780304 | -12.342068 | -28.586242 | -1.607962 |
| `stop_entry__opposite_ib__ladder__slip1` | 162 | 0.782901 | -30.507068 | -64.256491 | -1.513338 |
| `stop_entry__opposite_ib__overnight__slip1` | 82 | 0.768163 | -12.349878 | -14.883559 | -1.093176 |

## Expanding walk-forward — locked IS champion

| window | test span | trades | PF | expectancy ($) |
|---:|---|---:|---:|---:|
| 1 | 2025-07-17 → 2025-09-11 | 40 | 0.986034 | -0.545 |
| 2 | 2025-09-12 → 2025-11-06 | 39 | 0.803957 | -10.586667 |
| 3 | 2025-11-07 → 2026-01-08 | 39 | 0.643846 | -24.785385 |
| 4 | 2026-01-09 → 2026-03-09 | 38 | 0.637325 | -24.446316 |
| 5 | 2026-03-10 → 2026-05-05 | 39 | 1.196024 | 11.368462 |
| 6 | 2026-05-06 → 2026-05-29 | 17 | 0.64799 | -25.611176 |

## Resolution/terminal-window sensitivity

The wider 15-minute cache contains **437 complete sessions**. It is lower-resolution and not merged with the 5-minute source. Applying the locked champion produced PF **0.948701**, expectancy **$-3.092535**, CAGR **-7.69948%**, and max DD **40.584737%**.

**Data caveat:** the source is a stitched, non-back-adjusted continuous MES series. Roll transitions can affect overnight references; the conservative REJECT verdict is not a promotion claim.

## Criteria

```json
{
  "oos_sample_at_least_60": true,
  "oos_cagr_positive": false,
  "oos_pf_above_1": false,
  "campaign_dsr_at_least_0_95": false,
  "plus_one_tick_stress_expectancy_positive": false,
  "disjoint_halves_positive": false,
  "expectancy_beats_simple_ib_baseline": false
}
```

## Reproduce

```bash
env -u PYTHONPATH API_KEY='local-research-sandbox-dummy-not-a-credential' engine/.venv/Scripts/python.exe engine/backtest/research/run_mes_ib_vwap_basis.py --out-dir .hermes/artifacts/mes_ib_vwap_basis_20260927
```

Raw evidence: `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase1_mes_ib_ladder.json` and CSV sidecars.
