---
description: Walk-forward efficiency snapshot for a symbol. Pulls latest WFE snapshot from /wfe/snapshots and compares against paper-approval thresholds (MCL≥0.82, MNQ≥0.57, MES≥0.20 bypass). Read-only.
allowed-tools: Bash(curl:*), Read
argument-hint: "<symbol: MCL|MNQ|MES>"
---

# WFE Check

**Symbol**: $ARGUMENTS

Refuse to proceed if no symbol given. Must be one of MCL, MNQ, MES.

## Steps

1. Fetch latest WFE snapshots:
   ```bash
   API_KEY="${JARVIS_API_KEY}"
   curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/wfe/snapshots?symbol=$ARGUMENTS&limit=5"
   ```

2. If endpoint 404s or array empty → report "no WFE snapshots for $ARGUMENTS — run POST /wfe/snapshot first" and exit.

3. Extract from the newest entry: `wfe`, `oos_pf`, `oos_sharpe`, `oos_return`, `timestamp`, `timeframe`.

4. Compare to paper-approval thresholds (hardcoded in engine/config.py, do NOT re-query):
   - MCL: WFE ≥ 0.82
   - MNQ: WFE ≥ 0.57
   - MES: WFE ≥ 0.20 (owner bypass active — flag as "bypass")

5. Output:
   ```
   ## WFE Snapshot — $ARGUMENTS (<timeframe>)

   - Timestamp: <iso>
   - WFE: <value>  (threshold: <thr>)
   - OOS Profit Factor: <value>
   - OOS Sharpe: <value>
   - OOS Return: <pct>
   - Verdict: <PASS|FAIL|BYPASS-ACTIVE>
   ```

6. If the snapshot is older than 14 days, append: `stale — consider POST /wfe/snapshot to refresh`.

## Constraints

- Read-only. Do NOT call POST /wfe/snapshot or POST /wfe/optimize-bayesian from this command.
- If Matt wants a refresh, tell him to run `POST /wfe/snapshot` manually or use a separate command — WFE runs can be minutes long and shouldn't hide inside a quick check.

## Why this exists

Pattern source: `gianfrancopiana/openclaw-autoresearch` (single-status snapshot idea — their `autoresearch_status` tool returns current loop state). jarvis-trader's `/wfe/snapshots` endpoint exists (verified at `engine/routers/wfe_router.py:250`) but there was no slash command to pull the latest snapshot and compare it to the paper-approval gates.
