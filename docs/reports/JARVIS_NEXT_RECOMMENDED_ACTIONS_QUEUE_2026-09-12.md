# JARVIS Next Recommended Actions Queue — 2026-09-12

Generated: `2026-09-12T04:39:54.880808+00:00`

> Scope: safe docs/evidence/scripts and future read-only dashboard UI planning. No live trading, risk, kill-switch, `.env`, broker-routing, or symbol-routing changes are authorized here. MCL/MNQ remain DO_NOT_TRADE; no operational actions for them.

## Current evidence baseline

### Runtime/readiness

- operator_analysis_ready: **True**
- monitoring_ready: **False**
- execution_ready: **False**
- dashboard_ok: **True**
- engine_ok: **True**
- current actionable recommendations: **0** shown / **25** raw
- pending approvals: **0**

Blockers:
- kill_switch_active=true
- live_trading=false
- master-api :8030 closed; master/trade-record widgets may be degraded
- MES_1h active/auth mismatch: status=ACTIVE verdict=FAIL

### Recommendation attribution

- recommendation_attribution_proven: **True**
- queue_order_id_attribution_proven: **False**
- unique linked paper trades: **62**
- linked RTH paper trades: **20**
- queue order-id matches to paper: **0**
- linked closed P&L: **$4758.66**
- linked PF: **2.3703**
- linked win rate: **0.3333**
- RTH linked P&L: **$1885.33**
- RTH linked PF: **5.9318**

## Ranked top-10 queue

| Rank | Action | Why | Scope | Verification |
|---:|---|---|---|---|
| 1 | Preserve the two-lane audit split as canonical | Runtime health and recommendation edge are different truth problems | docs/scripts | Both latest JSON reports parse and disagree/agree explicitly |
| 2 | Create a clean PR/worktree lane for report scripts | Current serving repo has extensive unrelated dirty state; a commit here would be unsafe | git/docs/scripts | clean worktree + scoped diff only |
| 3 | Add durable recommendation lineage design memo | Queue `order_id` has 0 matches to paper trades; attribution is incomplete | docs/schema proposal only | memo cites exact DB fields and no runtime changes |
| 4 | Build baseline comparison script | Positive linked ledger is not edge without random/BH/time-matched baselines | scripts/reports | baseline JSON + P&L/expectancy table |
| 5 | Add read-only dashboard readiness badge plan | Operator needs `operator_analysis_ready` vs `monitoring_ready` vs `execution_ready` visible | dashboard plan only until clean lane | UI spec + Playwright plan |
| 6 | Add RTH/ETH split to dashboard scorecard plan | RTH-linked cohort differs materially from all paper trades | dashboard plan/report | RTH counts reconcile to attribution JSON |
| 7 | Restore/verify Master API dependency separately | `:8030` closed degrades master/trade-record widgets | separate ops lane | local health + dashboard proxy smoke |
| 8 | Add scheduled read-only audit job proposal | Keeps current state from going stale before market use | cron proposal only | existing jobs listed; one-writer rule verified |
| 9 | Add source-integrity stamp to reports | Distinguish serving tree from VCS truth | scripts/report | report includes git HEAD/status hash |
| 10 | Promote only after safety-review if execution gating changes | Recommendation-quality gates can affect routing | [safety-review] PR only | explicit PR + human approval |

## Recommended next batch

Create a clean, no-push local PR lane that contains only:

- `scripts/jarvis_dashboard_recommendation_audit.py`
- `scripts/jarvis_recommendation_attribution_audit.py`
- `docs/plans/2026-09-11-jarvis-readiness-recommendation-loop-implementation-strategy.md`
- `docs/reports/JARVIS_*_LATEST.*` report examples
- `docs/reports/JARVIS_NEXT_RECOMMENDED_ACTIONS_QUEUE_2026-09-12.md`

Then run targeted compile/report verification there. Do not push/open PR until explicitly authorized.
