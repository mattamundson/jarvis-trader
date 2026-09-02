# A-01 Runtime Snapshot Tool — Validation Receipt

**Plan:** JARVIS-MIP-1.0  
**WP:** A-01  
**Tool:** `scripts/phase0_runtime_truth_snapshot.py`  
**Commit:** `d0cf3c4c724af83b3936a8feb7e023dd4d8b8234`  
**Validation:** 2026-09-01

## Static/synthetic validation performed

1. Python source compiled successfully with `compile(..., mode="exec")` under a synthetic module path.
2. The configuration sanitizer was exercised with a synthetic payload containing:
   - `MAX_DAILY_LOSS_PCT=0.06`
   - `LIVE_TRADING_ENABLED=False`
   - `IB_PAPER_BROKER_ENABLED=True`
   - `JARVIS_LLM_PROVIDER=ollama`
   - a synthetic masked `API_KEY`
   - a synthetic broker account identifier
   - a synthetic user-specific SQLite path
3. Only the explicitly approved safe fields survived; the API key, account ID and DB path did not.
4. The health sanitizer was exercised with safe execution fields plus synthetic free-form `detail` and account data. Safe `status`, `execution_path.simulated`, `execution_path.broker_ack`, and `source` survived; free-form detail/account values did not.

## Evidence level

- **Syntax/static:** PASS.
- **Synthetic redaction behavior:** PASS.
- **Actual Windows runtime/API capture:** **UNVERIFIED — requires one execution against the running local engine.**

The tool is read-only by construction: it performs GET requests and TCP reachability probes only and does not import engine modules or call mutation endpoints.

## Operator command

From repository root:

```powershell
engine\.venv\Scripts\python scripts\phase0_runtime_truth_snapshot.py
```

Expected output artifact (git root, intentionally uncommitted unless reviewed):

```text
phase0_runtime_truth_snapshot.json
```

A-01 remains IN_PROGRESS until the resulting safe artifact is interpreted against the contradiction register.
