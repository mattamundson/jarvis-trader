# Dashboard readiness badge scorecard spec — 2026-09-12

## Scope
Read-only dashboard-dev plan/spec. No runtime dashboard component is changed in this pass.

## Current display problem
Operator readiness, monitoring readiness, and execution readiness are different states. A single green dashboard health check can hide execution blockers (`live_trading=false`, `kill_switch_active=true`, closed/absent dependencies, lineage gaps).

## Proposed badges

| Badge | Meaning | Current verified value |
|---|---|---|
| `Operator analysis ready` | Dashboard + engine can support paper/research/operator analysis | `True` |
| `Monitoring ready` | Monitoring dependencies are healthy enough for unattended trust | `False` |
| `Execution ready` | Live/paper execution path is fully eligible | `False` |
| `Recommendation attribution` | Paper trades can be linked to recommendation/approval source | `True` |
| `Queue-order lineage` | Queue `order_id` directly matches paper ledger | `False` |

## UX rule
Use explicit degraded copy instead of optimistic color:

- Analysis badge can be green when dashboard and engine are reachable.
- Monitoring badge should be amber/red if source freshness, master-api, TradingView CDP, or scheduled snapshot truth is degraded.
- Execution badge must be red/blocked while `live_trading=false` or `kill_switch_active=true`.
- Recommendation attribution badge can be green for linked ledger evidence.
- Queue-order lineage badge must be amber/red until direct order lineage exists.

## Data contract
Prefer an existing or new read-only JSON artifact from `scripts/jarvis_dashboard_recommendation_audit.py` with:

```json
{
  "operator_analysis_ready": true,
  "monitoring_ready": false,
  "execution_ready": false,
  "recommendation_attribution_proven": true,
  "queue_order_id_attribution_proven": false,
  "blockers": ["kill_switch_active=true", "live_trading=false"]
}
```

## Verification plan
1. Unit/JSON parse: latest readiness + attribution JSON reports parse and include all required fields.
2. Component smoke: card renders all five badges from fixture data.
3. E2E route smoke: dashboard route shows blocked execution without white-screening.
4. Safety grep: no edits to `engine/config.py`, `engine/risk/**`, kill-switch code, `.env*`, broker execution, or symbol gates.

## Recommendation
Implement the actual dashboard component only in the next clean UI tranche after this report lane is checkpointed, because current primary value is truthful evidence packaging and the canonical serving tree remains dirty/serving-first.
