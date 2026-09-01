# Pass 8 - VWAP Runner Bounds And Smoke Evidence

Date: 2026-09-01

## Scope

This pass converted the MES VWAP rank1 Gate-v2 runner from an opaque full-run-only script into an observable runner with explicit bounded diagnostic controls.

## Changes

- Added line-buffered console output to `engine/backtest/run_mes_vwap_rank1.py` so long foreground runs emit progress promptly.
- Added `--smoke`, `--max-windows`, `--max-grid-combos`, `--skip-fixed-sweep`, `--skip-cost-sweep`, and `--output-suffix`.
- Preserved canonical behavior: an unbounded run still writes `engine/data/gate_v2_verdicts/MES_vwap_rank1.json`.
- Bounded runs write suffixed artifacts such as `MES_vwap_rank1_smoke.json` and include `canonical: false` plus `certification_complete: false`.
- Added unit coverage in `engine/tests/test_run_mes_vwap_rank1_cli.py` for smoke, bounded, canonical, and invalid-bound behavior.

## Smoke Evidence

Command:

```powershell
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' backtest/run_mes_vwap_rank1.py --smoke
```

Result:

- Completed successfully in 34.3 seconds.
- Wrote `engine/data/gate_v2_verdicts/MES_vwap_rank1_smoke.json`.
- Artifact metadata:
  - `canonical: false`
  - `certification_complete: false`
  - `run_mode: smoke`
  - `windows_evaluated: 1`
  - `windows_available: 28`
  - `grid_combos_evaluated: 4`
  - `grid_combos_available: 36`
  - `skip_fixed_sweep: true`
  - `skip_cost_sweep: true`

## Verification

```powershell
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe' -m ruff check backtest/run_mes_vwap_rank1.py tests/test_run_mes_vwap_rank1_cli.py
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' -m pytest tests/test_run_mes_vwap_rank1_cli.py
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' -m py_compile backtest/run_mes_vwap_rank1.py
```

Result:

- Ruff passed.
- Python 3.12 compile passed.
- Pytest passed: 4 tests.

## Remaining Blocker

P3-004 remains blocked as a canonical certification task. The smoke artifact proves the patched semantics and Python 3.12 runtime can execute the runner, but it does not satisfy the acceptance criterion because the full unbounded runner still needs profiling or optimization before it can reliably write the canonical verdict artifact.

## Next Highest-ROI Work

1. Run the affected Initial Balance validation under patched point-in-time semantics.
2. Profile the full VWAP runner to locate the dominant runtime cost.
3. Optimize the full VWAP runner only where profiling shows material payoff.
4. Rerun the full canonical VWAP certification after the runtime blocker is removed.
