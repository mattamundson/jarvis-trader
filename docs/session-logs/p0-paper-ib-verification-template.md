# P0 — Paper IB verification evidence (template)

**Copy this file** to `p0-paper-ib-verification-YYYY-MM-DD.md` when you complete the runbook.

**Runbook:** [docs/runbooks/P0_PAPER_IB_VERIFICATION.md](../runbooks/P0_PAPER_IB_VERIFICATION.md)

## Environment

| Field | Value |
|-------|-------|
| Date (UTC) | |
| Engine base URL | |
| IB Gateway host:port | (paper default **4002**) |
| Operator | |

## Automated script output

Paste JSON from:

```powershell
cd engine
$env:JARVIS_API_KEY = "<engine API_KEY>"
$env:CHECK_IB_PORT = "1"
.venv\Scripts\python scripts\verify_p0_paper_ib.py
```

```json

```

## Manual checklist

| Step | Pass / N/A | Notes |
|------|------------|-------|
| §2 IB Gateway reachable | | |
| §3 SoT (A/B/A+B) chosen | | |
| §4 Dashboard proxy + API key | | |
| §5 Order smoke (optional) | | |

## Verdict

- [ ] **P0-1 satisfied** for this environment (link this file from strategic spine / session handoff if desired).
