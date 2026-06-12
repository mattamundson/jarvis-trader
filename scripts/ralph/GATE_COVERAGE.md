# US-007 Gate Coverage — Run-12 QuantStats Validation Gates

Verified: 2026-06-12. Branch: `ralph/edge-24x7`.

## Coverage Table

| Gate | Spec (Run-12) | Implemented? | File : line / dict |
|---|---|---|---|
| `sortino >= 1.0` (iteration) | YES | YES | `scripts/eval_run.py` : `ITERATION_GATES` |
| `sortino >= 1.5` (production) | YES | YES | `scripts/eval_run.py` : `PRODUCTION_GATES`; `scripts/jarvis_tearsheet.py:52` |
| `calmar >= 0.5` (iteration) | YES | YES | `scripts/eval_run.py` : `ITERATION_GATES` |
| `calmar >= 1.0` (production) | YES | YES | `scripts/eval_run.py` : `PRODUCTION_GATES`; `scripts/jarvis_tearsheet.py:53` |
| `tail_ratio >= 1.0` | YES | YES | `scripts/eval_run.py` : `ITERATION_GATES` + `PRODUCTION_GATES`; `scripts/jarvis_tearsheet.py:56` |
| `exposure >= 0.15` (iteration) | YES | **ADDED** (US-007) | `scripts/eval_run.py` : `ITERATION_GATES` |
| `exposure >= 0.20` (production) | YES | YES | `scripts/jarvis_tearsheet.py:60`; **ADDED** to `PRODUCTION_GATES` |
| `gain_to_pain >= 0.50` (iteration) | YES | YES | `scripts/eval_run.py` : `ITERATION_GATES` |
| `gain_to_pain >= 0.70` (production) | YES | YES | `scripts/eval_run.py` : `PRODUCTION_GATES`; `scripts/jarvis_tearsheet.py:59` |
| `consecutive_losses <= 8` (iteration) | YES | YES | `scripts/eval_run.py` : `ITERATION_GATES` |
| `consecutive_losses <= 6` (production) | YES | YES | `scripts/eval_run.py` : `PRODUCTION_GATES` |
| `skew >= -1.5` | YES | **ADDED** (US-007) | `scripts/eval_run.py` : `ITERATION_GATES` + `PRODUCTION_GATES` |
| `profit_factor` | existing | YES | all gate dicts |
| `win_rate` | existing | YES | all gate dicts |
| `max_drawdown` | existing | YES | all gate dicts |

## QS Function Availability

All Run-12 metric functions confirmed present in the installed quantstats package:

```
['sortino', 'calmar', 'tail_ratio', 'gain_to_pain_ratio', 'consecutive_losses', 'skew', 'exposure']
```

Run: `engine/.venv/Scripts/python.exe -c "import quantstats as qs; print([f for f in [...] if hasattr(qs.stats,f)])"`

All metrics are computed in `engine/reports/quantstats_metrics.py` via `_safe()` wrapper and
returned in the `extended` dict (lines 348-372). `skew` is at line 354; `exposure` at line 360.
`consecutive_losses` has its own typed handling at lines 340-346.

## Metric computation coverage (quantstats_metrics.py)

| Metric | Key | Location |
|---|---|---|
| sortino | `sortino` | line 312 |
| calmar | `calmar` | line 314 |
| tail_ratio | `tail_ratio` | line 353 |
| exposure | `exposure` | line 360 |
| gain_to_pain | `gain_to_pain` | line 351 |
| consecutive_losses | `consecutive_losses` | lines 340-346 |
| skew | `skew` | line 354 |

## Changes Made (US-007 upgrade)

Two gates were genuinely absent from `scripts/eval_run.py` ITERATION_GATES and PRODUCTION_GATES:

1. `skew >= -1.5` — was diagnostic-only (printed but not gated); promoted to gate in both dicts
2. `exposure >= 0.15` (iteration) / `>= 0.20` (production) — present in `jarvis_tearsheet.py`
   PRODUCTION_GATES but absent from `eval_run.py`; added to both dicts

**File changed:** `scripts/eval_run.py` (ITERATION_GATES lines 37-58, PRODUCTION_GATES lines 48-58)
**No thresholds were loosened.** All existing gates retained at or above original spec.
**Fail-safe intact:** `None` metric value → `failures.append(f"{gate}: MISSING")` → exit 1 (NO_TRADE).

## Test coverage

New test file: `engine/tests/test_eval_run_gates.py` (8 tests)

- Gate completeness: all Run-12 keys present in both dicts at correct thresholds
- Threshold regression: no existing gate was loosened
- Logic smoke tests: skew and exposure gates fire correctly against synthetic returns

Pytest result: **8 passed** in 3.81s. Ruff: **All checks passed**.

## Verdict

**US-007 SATISFIED** (with minor upgrade). Core QS machinery was fully in place.
`skew` and `exposure` were the only genuinely missing gates in `eval_run.py`.
All other Run-12 gates were already implemented across the three gate locations.
