# A-01 Runtime Snapshot Tool — Validation Receipt

**Plan:** JARVIS-MIP-1.0  
**WP:** A-01  
**Tool:** `scripts/phase0_runtime_truth_snapshot.py`  
**Candidate head:** `PR #769`  
**Validation:** 2026-09-02  
**State:** E0 PASS / E1 PENDING CI / ACTUAL RUNTIME UNVERIFIED

## Security correction from the PR #760 prototype

The prototype accepted an arbitrary `--engine-url` while attaching the configured API key. A malicious or mistaken remote URL could therefore receive that credential. That implementation must not be merged.

PR #769 changes the boundary to:

- HTTP(S) loopback hosts only: `127.0.0.1`, `::1`, or `localhost`;
- no URL userinfo, path, query, or fragment;
- only six allowlisted GET endpoints;
- no engine imports or mutation methods;
- no API key, broker account identifier, DB path, or unallowlisted free text in the artifact;
- exclusive create by default and explicit atomic `--force` replacement;
- generated artifact ignored by Git.

## Static and synthetic validation

1. Python byte compilation: PASS.
2. Manual loopback URL allow/deny assertions: PASS.
3. Manual health sanitization assertion: PASS.
4. Source line-length check at 100 characters: PASS.
5. Focused pytest coverage is committed for:
   - loopback-only URLs;
   - GET-only allowlisted endpoints;
   - secret/account/path/free-text redaction;
   - API-key omission from serialized output;
   - overwrite refusal and explicit force;
   - stdlib-only/no-engine-import/no-mutation source invariants.
6. The transient scratch runtime did not contain pytest, so no local pytest result is claimed. GitHub CI on PR #769 is the authoritative E1 receipt.

## Operator command after merge

From repository root on the actual JARVIS host:

```powershell
engine\.venv\Scripts\python scripts\phase0_runtime_truth_snapshot.py
```

Review `phase0_runtime_truth_snapshot.json` locally before sharing it.

## Claim boundary

The tool can collect evidence but cannot interpret or authorize it. A-01 remains **IN PROGRESS** until an operator runs the reviewed version against the real runtime and assigns every contradiction one of:

- `RESOLVED`
- `SUPERSEDED`
- `BLOCKING`
- `ACCEPTED_RISK`

Actual Windows processes, loaded risk values, broker mode/account, SQLite state, current eligibility, and market-data freshness are **UNVERIFIED**.
