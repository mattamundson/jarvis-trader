# Pass 12 - Environment Drift Detector

Date: 2026-09-01

## Scope

This pass implemented the lightweight environment drift detector planned in P4-006.

## Changes

- Added `engine/scripts/check_environment_drift.py`.
- Added `engine/tests/test_environment_drift.py`.
- Detector is read-only: it does not start, stop, or restart runtime services.
- Detector emits JSON and writes the latest local proof to `engine/data/health/environment_drift_latest.json`.
- Detector exits non-zero when hard drift is present.

## Checks

The detector checks:

- Active Python interpreter is `3.12.x`.
- `engine/.venv/Scripts/python.exe` is `3.12.x`.
- `engine/.venv312-codex-loop/Scripts/python.exe` is available as the parallel proof venv.
- Node major version is at least 20.
- pnpm major version is at least 9.
- Dashboard `dev` and `start` scripts pin port `3010`.
- Engine docs/start command pin port `8010`.
- `engine/config.py` defaults live trading off and IBKR to paper port `4002`.
- Dashboard exposes the `guards` script.

## Verification

```powershell
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe' -m ruff check scripts/check_environment_drift.py tests/test_environment_drift.py
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' -m pytest tests/test_environment_drift.py
```

Result:

- Ruff passed.
- Pytest passed: 5 tests.

## Local Proof

Command:

```powershell
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' scripts/check_environment_drift.py
```

Result:

- Exit code: `1`
- Status: `fail`
- Summary: `total=9`, `passed=8`, `hard_failures=1`, `warnings=0`
- Hard failure:
  - `engine_venv_python`: `engine/.venv` reports `Python 3.13.3`; expected `Python 3.12.x`.

All other checks passed:

- Active proof interpreter: `Python 3.12.10`
- Parallel proof venv: `Python 3.12.10`
- Node: `v24.15.0`
- pnpm: `10.33.2`
- Dashboard port: `3010`
- Engine port: `8010`
- Safety defaults: live trading off, IBKR paper port `4002`
- Dashboard guard script present

## Backlog Impact

- P6-007 can be marked done.
- P6-008 can be marked done.
- P6-009 can be marked done.
- The known Python 3.13 active venv drift remains a concrete environment repair task, but the detector now makes it visible and machine-checkable.
