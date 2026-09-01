# Pass 4 Data Semantics and Inventory - 2026-09-01

Loop: `jarvis-master-plan-drain-20260901`

## Scope

Complete the remaining pass-2 backlog items with low coordination risk:

- Patch Initial Balance point-in-time leakage.
- Patch VWAP RTH anchoring and signal eligibility.
- Confirm engine Python-version drift without rebuilding the venv.
- Re-classify PR #749 check state from GitHub.
- Create compact runtime/API/dashboard/worktree inventory.

## Data Semantics Fixes

| File | Change |
|---|---|
| `engine/backtest/ib_signals.py` | Added an explicit post-IB-window mask so premarket and in-window rows cannot see the completed same-session IB high/low. |
| `engine/tests/test_ib_signals.py` | Added regression coverage proving premarket rows get `NaN` IB levels and no breakout flags while post-IB rows retain frozen levels. |
| `engine/backtest/vwap_signals.py` | Replaced hour-only VWAP reset with Eastern session metadata. VWAP now accumulates only during 09:30-16:00 ET and new signals are eligible only during 09:30-15:00 ET. |
| `engine/tests/test_vwap_signals.py` | Added offline synthetic tests for no pre-RTH VWAP exposure and no repeated 09:xx reset on sub-hour bars. |

## VWAP Exposure Quantification

Latest MES 1h cache inspected:

```text
engine/backtest/cache/MES_2019-05-05_2026-08-26_1h.csv
rows: 43,010
range: 2019-05-05 22:00:00+00:00 to 2026-08-26 20:00:00+00:00
```

Direct eligibility and patched-baseline evidence:

```text
old hour-only semantics: 18,902 bars were signal-eligible outside 09:30-15:00 ET
patched baseline signals: 17
patched baseline outside-window signals: 0
patched baseline pre-RTH VWAP values: 0
```

[RISK] Prior VWAP strategy verdicts should not be treated as certified under the patched semantics until Gate-v2/PBO/DSR is rerun and verdict flips are reviewed.

## Environment Drift

The active engine venv reports:

```text
C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe
Python 3.13.3
```

Repo and CI references still target Python 3.12:

- `.github/workflows/ci.yml`
- `.github/workflows/es-research-platform.yml`
- `.github/workflows/p0-verify.yml`
- `engine/pyproject.toml` mypy `python_version = "3.12"`
- `dashboard/AGENTS.md`
- `docs/CURRENT_STATE.md`

No venv rebuild was performed in this pass.

## PR #749 Check State

`gh pr checks 749 --repo mattamundson/jarvis-trader` reports immediate failures in:

- Dashboard Quality
- Engine Draft Check
- Focused engine research checks
- Platform format/lint/types/tests/CLI smoke
- Safety-critical config gate

The check surface is classified, but root cause is still not fully proven because GitHub logs were not available through the earlier `gh run view --log-failed` attempt.

## Runtime Surface Inventory

Created `RUNTIME_SURFACE_INVENTORY_2026-09-01.json`.

Highlights:

- Engine router route decorators: 420.
- Dashboard app route files: 61.
- Worktrees: 28 total, 15 clean, 13 dirty, 3 detached, 1 locked, 1 prunable.

No worktrees were archived, pruned, deleted, checked out, or reset.

## Verification

Focused lint:

```text
engine/.venv/Scripts/ruff.exe check backtest/ib_signals.py backtest/vwap_signals.py tests/test_ib_signals.py tests/test_vwap_signals.py --config ruff.toml
Result: All checks passed.
```

Focused tests:

```text
engine/.venv/Scripts/python.exe -m pytest tests/test_ib_signals.py tests/test_vwap_signals.py -q
Result: 11 passed, 1 warning.
```

## Next Highest-ROI Tasks

1. Run the full focused verification bundle covering pass 3 and pass 4 touched files.
2. Commit the plan package and CI/data-semantics fixes in path-bounded local commits.
3. Rebuild or create a Python 3.12 engine venv in a reversible way, then rerun focused tests under 3.12.
4. Rerun MES VWAP Gate-v2/PBO/DSR under patched RTH semantics and compare verdicts.
5. Rerun affected IB strategy validation and compare verdicts.
