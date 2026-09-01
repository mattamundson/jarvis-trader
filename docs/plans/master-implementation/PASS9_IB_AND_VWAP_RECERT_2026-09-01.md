# Pass 9 - IB And VWAP Recertification

Date: 2026-09-01

## Scope

This pass reran the affected Initial Balance validations after the point-in-time fix, profiled the blocked MES VWAP rank1 validation, optimized the VWAP hot path, and completed the canonical VWAP Gate-v2 recertification.

## Initial Balance Recertification

Command:

```powershell
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' backtest/ib_wfo_runner.py
```

Generated local artifacts:

- `engine/data/gate_v2_verdicts/MES_ib_go_rank1.json`
- `engine/data/gate_v2_verdicts/MES_ib_fade_rank1.json`
- `engine/data/gate_v2_verdicts/MGC_ib_go_rank1.json`
- `engine/data/gate_v2_verdicts/MGC_ib_fade_rank1.json`

Result summary:

| Artifact | Verdict | Key Metrics |
|---|---:|---|
| `MES_ib_go_rank1.json` | FAIL | `pf_ci_lower=0.8222`, `p_edge=0.4`, `dsr=0.0`, `wfo=WEAK`, `total_oos_trades=357` |
| `MES_ib_fade_rank1.json` | FAIL | `pf_ci_lower=0.7347`, `p_edge=0.6`, `dsr=0.0`, `wfo=MODERATE`, `total_oos_trades=349` |
| `MGC_ib_go_rank1.json` | FAIL | `pf_ci_lower=1.0433`, `p_edge=0.5714`, `dsr=0.884911`, `wfo=MODERATE`, `total_oos_trades=254` |
| `MGC_ib_fade_rank1.json` | FAIL | `pf_ci_lower=0.6776`, `p_edge=0.4286`, `dsr=0.0`, `wfo=WEAK`, `total_oos_trades=309` |

Repository note: these JSON artifacts are intentionally ignored by `.gitignore`; this report records their parsed evidence instead of force-adding generated files.

## VWAP Profiling

Pre-optimization smoke run:

- `--smoke` completed in 34.3 seconds.
- `cProfile` reported 5 VWAP backtests consuming 23.3 seconds, with repeated pandas scalar access inside `vwap_backtester.py` and `vwap_signals.py` as the dominant avoidable cost.

Post-first optimization:

- `vwap_backtester.py` hot loop converted repeated scalar reads to one-time arrays.
- Smoke run improved to 23.2 seconds.
- Profile then showed `generate_vwap_signals` as the remaining dominant repeat cost.

Post-second optimization:

- `vwap_signals.py` session VWAP and signal loops now use array reads and array-backed output writes.
- Smoke run improved to 15.4 seconds.

## Canonical VWAP Recertification

Command:

```powershell
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' backtest/run_mes_vwap_rank1.py
```

Local run logs:

- `engine/backtest/results/20260901_vwap_rank1_full.out.log`
- `engine/backtest/results/20260901_vwap_rank1_full.err.log`

Generated local artifact:

- `engine/data/gate_v2_verdicts/MES_vwap_rank1.json`

Verdict:

- `verdict: FAIL`
- `canonical: true`
- `certification_complete: true`
- `pf_ci_lower: 0.5729`
- `p_edge: 0.4118`
- `mc_95th_dd_pct: 7.4680`
- `dsr: 0.0`
- `wfo_consistency: WEAK`
- `fixed_params_min_pf: 0.2600`
- `cost_survives_through: none`
- `n_oos_windows_with_trades: 17`
- `n_oos_windows: 28`
- `total_oos_trades: 237`

Conclusion: MES VWAP rank1 remains rejected under Gate v2 after the RTH semantics patch. The canonical failure agrees with the older legacy WFE rejection, but now has current Gate-v2 provenance.

## Verification

```powershell
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe' -m ruff check backtest/run_mes_vwap_rank1.py backtest/vwap_backtester.py backtest/vwap_signals.py tests/test_run_mes_vwap_rank1_cli.py tests/test_vwap_signals.py
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' -m pytest tests/test_run_mes_vwap_rank1_cli.py tests/test_vwap_signals.py
```

Result:

- Ruff passed.
- Pytest passed: 6 tests.

## Backlog Impact

- P3-004 can be marked done.
- P3-005 can be marked done.
- P5-003 through P5-006 can be marked done.
- Next recommended work should move back to PR/CI convergence and Command Center implementation sequencing.
