# Pass 6 Python 3.12 Proof - 2026-09-01

Loop: `jarvis-master-plan-drain-20260901`

## Scope

Create and prove a parallel Python 3.12 engine environment without replacing the active `engine/.venv`.

## Result

Created:

```text
C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop
```

Interpreter:

```text
Python 3.12.10
```

Install:

```text
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r engine/requirements-core.txt
```

Install completed successfully. `pip` reported that `aiohttp==3.11.14` is yanked upstream because of an upstream regression. `pip check` still reports:

```text
No broken requirements found.
```

## Verification

Focused loop tests under Python 3.12:

```text
engine/.venv312-codex-loop/Scripts/python.exe -m pytest tests/test_latency_fixes_20260818.py tests/test_ib_signals.py tests/test_vwap_signals.py -q
Result: 16 passed in 7.08s
```

## Current Environment State

- `engine/.venv` remains unchanged and still points to Python 3.13.3.
- `engine/.venv312-codex-loop` is a proven parallel Python 3.12 environment.
- No engine or dashboard services were started or restarted.
- No venv archive/swap was performed.

## Next Use

Use `engine/.venv312-codex-loop/Scripts/python.exe` for validation reruns that should match CI's Python 3.12 target. Swap the active `.venv` only after a separate archive-first action.

