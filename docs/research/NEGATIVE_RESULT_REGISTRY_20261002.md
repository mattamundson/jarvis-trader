# JARVIS Negative-Result Registry

This registry prevents rejected MES hypotheses from being silently resurrected under a new filename or parameter label.

Machine-readable authority:

`engine/backtest/research/negative_results_registry.json`

Executable guard:

`engine/backtest/research/negative_results.py::assert_reopen_allowed`

## Retired results

| Candidate ID | Family | Feature | Verdict | Principal failure |
|---|---|---|---|---|
| `mes_ib_sequential_target_ladder` | Initial-balance ladder | Sequential targets | **REJECT** | Locked OOS PF 0.811870, expectancy −$11.913827/trade, Sharpe −1.330078, DSR 0 at 226 measured campaign trials; worse than simple IB-break baseline. |
| `mes_weekly_vwap_time_acceptance` | Weekly-VWAP acceptance | Time | **REJECT** | Did not beat both price-above-VWAP and unconditional baselines after multiplicity correction. |
| `mes_weekly_vwap_volume_acceptance` | Weekly-VWAP acceptance | Volume | **REJECT** | Raw improvement over the weak price baseline did not survive Holm correction and lost to the unconditional base rate. |
| `mes_weekly_vwap_developing_vpoc_acceptance` | Weekly-VWAP acceptance | Developing VPOC | **REJECT** | Failed paired Brier/multiplicity gates; OHLCV allocation is not exchange volume-at-price. |
| `mes_weekly_vwap_developing_tpo_poc_acceptance` | Weekly-VWAP acceptance | Developing TPO POC | **REJECT** | Did not beat both probability baselines after multiplicity correction. |
| `mes_weekly_vwap_ohlcv_clv_delta_acceptance` | Weekly-VWAP acceptance | CLV-volume delta proxy | **REJECT** | Failed predictive/economic gates; proxy is not true bid/ask cumulative delta. |

## Reopening contract

A retired candidate remains blocked unless all conditions are supplied:

1. a new dated preregistration identifier;
2. a materially different mechanism or dataset;
3. a new locked evaluation-window identifier;
4. no reuse of the rejected OOS window for optimization.

The guard fails closed when any condition is missing. Passing the guard authorizes research only; it does not authorize strategy promotion, engine integration, capital deployment, or order generation.

## Shared provenance

- Data: `MES_2024-09-22_2026-05-29_5m_cont.csv`
- SHA-256: `516beb11568f3270e595035b1dada669654c6b337f87b81b35fc386dff092a12`
- Actual span: 2024-09-22T22:00:00Z through 2026-05-29T20:55:00Z
- Rows: 119,096
- Complete causal sessions: 417
- Continuous series: stitched and not back-adjusted

The full evidence is in `docs/research/MES_IB_VWAP_BASIS_EXECUTIVE_20260927.md` and `.hermes/artifacts/mes_ib_vwap_basis_20260927/`.
