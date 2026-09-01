# Pass 10 - IB Runner Observability

Date: 2026-09-01

## Scope

This pass improved `engine/backtest/ib_wfo_runner.py` after the recertification run completed but initially returned through the harness timeout without useful foreground progress.

## Changes

- Enabled line-buffered stdout when the runtime supports `sys.stdout.reconfigure`.
- Replaced raw `sys.argv` branching with an `argparse` parser.
- Preserved backward-compatible positional usage:

```powershell
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' backtest/ib_wfo_runner.py MES go
```

- Added explicit option-based dispatch:

```powershell
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' backtest/ib_wfo_runner.py --symbol MES --mode go
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' backtest/ib_wfo_runner.py --symbol MES
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' backtest/ib_wfo_runner.py --mode fade
```

## Verification

```powershell
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe' -m ruff check backtest/ib_wfo_runner.py tests/test_ib_wfo_runner_cli.py
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' -m pytest tests/test_ib_wfo_runner_cli.py
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' backtest/ib_wfo_runner.py --help
```

Result:

- Ruff passed.
- Pytest passed: 6 tests.
- CLI help rendered with positional and option-based dispatch.

## Backlog Impact

- P6-002 can be marked done.
- P6-003 can be marked done.
- Next recommended task is the isolated PR #749 local commit and verification path.
