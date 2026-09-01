# Python 3.12 Venv Repair Plan - 2026-09-01

## Finding

The current engine virtual environment is not aligned with the repo/CI target:

```text
engine/.venv/Scripts/python.exe -> Python 3.13.3
```

Installed Python launchers:

```text
py -0p
-V:3.14 *        C:\Users\mattm\AppData\Local\Python\pythoncore-3.14-64\python.exe
-V:3.12          C:\Users\mattm\AppData\Local\Programs\Python\Python312\python.exe
-V:Astral/CPython3.11.15 C:\Users\mattm\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe
```

Shell command resolution:

```text
python.exe -> C:\Users\mattm\anaconda3\python.exe
python3.exe -> C:\Users\mattm\AppData\Local\Microsoft\WindowsApps\python3.exe
py.exe -> C:\Users\mattm\AppData\Local\Programs\Python\Launcher\py.exe
```

Repo target references:

- `.github/workflows/ci.yml` uses Python 3.12.
- `.github/workflows/es-research-platform.yml` uses Python 3.12.
- `.github/workflows/p0-verify.yml` uses Python 3.12.
- `engine/pyproject.toml` sets mypy `python_version = "3.12"`.
- `dashboard/AGENTS.md` describes the engine as Python 3.12.

## Reversible Repair Path

Do not overwrite `engine/.venv` first. Prove a parallel venv, then swap only if it passes.

1. Create a parallel venv:

```powershell
& "C:\Users\mattm\AppData\Local\Programs\Python\Python312\python.exe" -m venv "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop"
```

2. Upgrade packaging tools:

```powershell
& "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
```

3. Install the narrow dependency set first:

```powershell
& "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe" -m pip install -r "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\requirements-core.txt"
```

4. Run the focused loop verification:

```powershell
& "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe" -m pytest tests/test_latency_fixes_20260818.py tests/test_ib_signals.py tests/test_vwap_signals.py -q
```

5. If the parallel venv passes, archive the current venv before replacement:

```powershell
$archive = "C:\Users\mattm\Archive\2026\jarvis-trader-venv\engine-.venv-python313-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Force (Split-Path $archive) | Out-Null
Move-Item -LiteralPath "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv" -Destination $archive
Move-Item -LiteralPath "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop" -Destination "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv"
```

## Guardrails

- No deletion: archive the old `.venv`.
- No engine or dashboard restart as part of the venv swap.
- No live/paper order-path testing until engine health is checked after the swap.
- If dependency install fails, keep the current `.venv` in place and record the missing wheel or package conflict.

