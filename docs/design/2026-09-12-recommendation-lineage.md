# JARVIS recommendation lineage design memo — 2026-09-12

## Scope
Read-only design artifact for dashboard-dev. This memo proposes lineage and display changes only; it does **not** modify live trading, risk config, kill-switch state, broker execution, `.env`, or symbol gates.

## Current verified attribution state
Source: `docs/reports/JARVIS_RECOMMENDATION_ATTRIBUTION_AUDIT_LATEST.json`.

- `paper_rows`: **120**
- `pending_trade_approvals`: **373**
- `pipeline_approval_queue_rows`: **896**
- `pending_approval_paper_trade_id_links`: **1**
- `strategy_params_approval_id_links`: **61**
- `unique_linked_paper_trades`: **62**
- `unlinked_paper_trades`: **58**
- `queue_order_id_matches_to_paper`: **0**
- `linked_rth_paper_trades`: **20**

Linked-ledger economics are positive but incomplete as edge proof:

| Cohort | Closed | P&L | Win rate | Profit factor |
|---|---:|---:|---:|---:|
| all paper | 91 | $3181.32 | 0.3077 | 1.4211 |
| all unique linked | 42 | $4758.66 | 0.3333 | 2.3703 |
| RTH linked | 18 | $1885.33 | 0.4444 | 5.9318 |
| unlinked | 49 | $-1577.34 | 0.2857 | 0.6136 |
| queue order-id matched | 0 | $0 | None | None |

## Problem
The dashboard can truthfully say recommendation attribution exists via approval IDs, but it cannot yet prove queue-order lineage because `pipeline_approval_queue.order_id` has **0** matches to `paper_trades.trade_id` / `paper_trades.idempotency_key`.

That means current recommendation-performance UI must split:

1. **Linked paper-ledger evidence** — `62` linked paper trades, positive linked P&L.
2. **Queue-order lineage** — not proven; `0` direct order-id matches.
3. **Edge claim** — still unproven until lineage plus baseline comparison exists.

## Proposed safe schema additions
[SAFETY] Implement only in a dedicated reviewable PR and keep dashboard display read-only unless a later `[safety-review]` PR changes execution behavior.

Recommended lineage fields:

- `pipeline_approval_queue.recommendation_id` — stable queue recommendation ID.
- `pipeline_approval_queue.approval_id` — nullable link to `pending_trade_approvals.approval_id`.
- `pipeline_approval_queue.paper_trade_id` — nullable link to `paper_trades.trade_id` once paper execution records.
- `paper_trades.source_recommendation_id` — immutable recommendation source ID.
- `paper_trades.source_queue_id` — queue row ID or generated queue UUID.
- `paper_trades.source_pipeline_run_id` — link to the pipeline run that generated the recommendation.

## Dashboard display rule
Show three separate badges:

| Badge | True condition | Current value |
|---|---|---|
| Recommendation linked | `unique_linked_paper_trades > 0` | `true` |
| Queue-order lineage | `queue_order_id_matches_to_paper > 0` | `false` |
| Edge proven | lineage + baseline comparison + sufficient sample | `false` |

## Verification requirements before promoting to product UI
- Read-only audit script emits the three booleans above.
- JSON report parses and exact counts reconcile to raw DB tables.
- Dashboard card renders degraded/honest state when queue lineage is false.
- Playwright smoke asserts the card says queue-order lineage is not proven.
- No writes to engine/risk/kill-switch/broker/.env/symbol-gate files.
