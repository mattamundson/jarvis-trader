# jarvis-quant — sandbox

Throwaway learning sandbox for the IB Python API. **Not production.**

The production trading system lives at `C:\Users\mattm\ThinkorSwim\jarvis-trader\` —
this directory exists only to work through the Perplexity quant-bootstrap guide
without touching it.

## Why this exists

Following a step-by-step guide that assumes a greenfield ib_insync project. The
greenfield is fictitious for me (jarvis-trader is several phases past it), but
running through the guide hands-on is useful for building intuition about the
IB Python API, contract qualification, order placement, and connection
mechanics before extending the real system.

## Library choice — ib_async, not ib_insync

The guide says `pip install ib_insync`. This sandbox uses `ib_async` instead because:

1. `ib_async` is the actively maintained successor to `ib_insync` (original
   author paused work; community fork picked it up under a new name).
2. The public API is identical — every snippet from the guide works with
   `from ib_async import IB, Future, ...`.
3. jarvis-trader pins `ib_async==2.1.0` in `engine/requirements-core.txt`, so
   anything learned here transfers directly.

## Environment

- Python: **3.12.10** (via `py -3.12 -m venv .venv`) — matches jarvis-trader
- Activate: `.\.venv\Scripts\Activate.ps1` (PowerShell)
- Verify: `python _verify_imports.py`

The project venv at `.venv/` is the **only** supported environment. An older
conda env named `jarvis` (Python 3.11) was retired 2026-05-07 — anything
referencing it is stale. Reinstall `.venv` from `requirements.txt` if it gets
corrupted; do not recreate the conda env.

## Jupyter

- Kernel name: `jarvis-quant-venv` (display: `Python (jarvis-quant-venv)`)
- Registered against `.venv/` Python 3.12.10
- Launch JupyterLab from the venv:
  ```powershell
  .\.venv\Scripts\jupyter-lab.exe
  ```
- Notebooks under `research/` are pinned to the `jarvis-quant-venv` kernel
- Re-register the kernel if it disappears:
  ```powershell
  .\.venv\Scripts\python.exe -m ipykernel install --user --name jarvis-quant-venv --display-name "Python (jarvis-quant-venv)"
  ```

## Connection assumptions

| Broker | Default | Paper port | Live port |
|---|---|---|---|
| IB Gateway | installed at `C:\Jts\ibgateway\1046\` | 4002 | 4001 (blocked) |
| TWS | NOT INSTALLED on this machine | 7497 | 7496 |

The config (`config/broker_ibkr.yaml`) defaults to **Gateway paper on 4002**
because that's what's actually installed. Switch `target: tws` once TWS is
installed.

## clientId allocation

IBKR clientIds must be unique per concurrent connection to the same broker. jarvis-quant
scripts and jarvis-trader's engine both connect to IB Gateway on port 4002, so allocations
must not collide.

| clientId | Used by | Notes |
|---|---|---|
| 1 | `test_tws_connection.py` | Hardcoded test |
| 17 | `test_tws_connection_from_config.py` | Config-driven test (Perplexity tutorial default) |
| 22 | `test_es_contract.py` | ES futures contract qualification |
| 99 | `research/_pull_ibkr_bars.py` | Intraday IBKR bar pull |
| 100+ | Reserved | Future research scripts; avoid jarvis-trader's range |

**jarvis-trader's range:** 1-20 typical, up to 246 observed (rotation logic in
`restart_engine.ps1` — see `Using IBKR client ID:` line in startup logs).

**Before running concurrent IBKR scripts**, check the engine startup log for the current
clientId in use:

```powershell
Get-Content C:\Users\mattm\.claude\logs\engine-restart.out.log | Select-String 'IBKR client ID'
```

If the engine has rotated into the 99-150 range, bump your script's clientId to 200+.

**Symptom of clientId collision**: `IBKRError: Connection refused` or silent disconnect
~5 seconds after connect. The error message does NOT mention clientId; if you see it,
verify allocation first.

## Layout

```
config/                     broker_ibkr.yaml — host/port/client/contracts
src/                        sandbox modules (data, signals, portfolio, ...)
tests/                      connection + contract tests
research/                   notebooks, scratch
docs/                       guide notes
deploy/                     (unused for sandbox)
```

## Running the connection tests

Pre-flight (one of these must be true):
- IB Gateway running, logged into a paper account, "Enable ActiveX and Socket Clients" on, port 4002 confirmed in API settings
- TWS running (once installed), logged in to paper, port 7497 in API settings — and
  flip `config/broker_ibkr.yaml` `port_paper` to `7497`

Then, from `C:\Users\mattm\Code\jarvis-quant`:

```powershell
.\.venv\Scripts\python.exe _verify_imports.py                  # sanity-check the venv
.\.venv\Scripts\python.exe test_tws_connection.py              # hardcoded port test
.\.venv\Scripts\python.exe test_tws_connection_from_config.py  # config-driven
.\.venv\Scripts\python.exe test_es_contract.py                 # qualify ES futures
```

Expected first-run output: `CONNECTED OK` plus the managed paper account ID
(`DUP662235` based on current config).
