
# SWOT and strategy (TOWS)

**Sources:** Condensed from [INTEGRATED_ROADMAP_2026-04.md §6](../plans/INTEGRATED_ROADMAP_2026-04.md) and [MASTER_PROJECT_AUDIT_2026-04-04 §18](../reports/MASTER_PROJECT_AUDIT_2026-04-04.md).  
**Execution:** Map actions to [07_EXECUTION_SPINE.md](07_EXECUTION_SPINE.md) and [05_RISK_REGISTER.md](05_RISK_REGISTER.md).

---

## SWOT

### Strengths

| ID | Statement |
|----|-----------|
| S1 | Safety architecture: hardcoded Python safety layer; human approval; paper mode defaults. |
| S2 | Clear engine vs dashboard split; `fetchEngine` / `postEngine` boundary. |
| S3 | MES/MGC validated per policy and active on paper; MCL/MNQ halted (see validated-instruments). |
| S4 | Large pytest corpus and targeted integration tests (IB offline, middleware, approvals). |
| S5 | Runbooks and troubleshooting for real failures (OpenClaw, engine restart, Twilio). |

### Weaknesses

| ID | Statement |
|----|-----------|
| W1 | Two paper “worlds” possible: runner/JSON vs engine DB/API — divergence risk. |
| W2 | LLM dependency: cost, latency, billing; degraded analysis modes underdeveloped. |
| W3 | Broad router and feature surface vs small validated instrument set. |
| W4 | Operational fragility: IB, OAuth brokers, notifications, Windows elevation edge cases. |
| W5 | Structural debt: oversized `main.py`, large files — regression risk on refactor. |

### Opportunities

| ID | Statement |
|----|-----------|
| O1 | Unify paper ledger truth for dashboard + alerts (single spine). |
| O2 | Learning loop from structured events → recommendations (never override safety without Tier 3). |
| O3 | Stable health/safety JSON contracts + dashboard contract tests. |
| O4 | Research pipeline: WFE artifact + explicit approval before new symbols/timeframes. |
| O5 | Cost/latency telemetry and optional slim pipeline modes for outages (non-safety). |

### Threats

| ID | Statement |
|----|-----------|
| T1 | Pressure to go live before paper stats and ops are boringly stable. |
| T2 | Secrets in history/logs/transcripts — repeat of past incidents if discipline slips. |
| T3 | Regime change degrading parameters validated on historical windows. |
| T4 | Vendor/API drift (data, broker, model providers). |
| T5 | Overfitting spend on MES/MGC or symbols outside [.claude/imports/validated-instruments.md](../../.claude/imports/validated-instruments.md) policy. |

---

## TOWS — strategic actions

### SO (Strengths × Opportunities)

| Action | Uses | Pursuit |
|--------|------|---------|
| SO-1 | S1, S2, O3 | Lock health/safety response shapes; add contract tests for top dashboard paths. |
| SO-2 | S4, O1 | Define one E2E paper scenario test + runbook step that uses engine as SoT. |
| SO-3 | S3, O4 | Enforce instrument allowlist in API/UI where feasible; document exceptions. |

### WO (Weaknesses × Opportunities)

| Action | Addresses | Pursuit |
|--------|-----------|---------|
| WO-1 | W1, O1 | Document and implement default paper source; deprecate ambiguous dual paths. |
| WO-2 | W2, O5 | Pipeline profiling + billing alerts; degraded UX when LLM unavailable. |
| WO-3 | W5, O3 | Incremental extraction from `main.py` behind tests — no big-bang rewrite. |

### ST (Strengths × Threats)

| Action | Uses | Mitigates |
|--------|------|-----------|
| ST-1 | S1, S5 | Runbooks + drills for kill switch and restart; persist state where designed (see risk register). |
| ST-2 | S4, T2 | CI secret scan + no secrets in prompts/logs policy. |
| ST-3 | S3, T5 | Canon + gates: no production tuning on failed-WFE symbols. |

### WT (Weaknesses × Threats)

| Action | Addresses | Mitigates |
|--------|-----------|-----------|
| WT-1 | W3, T1 | Explicit non-goals in [01_EXECUTIVE_BRIEF.md](01_EXECUTIVE_BRIEF.md); Phase 3 checklist gating. |
| WT-2 | W4, T4 | IB reconnect + backup + monitoring tasks on execution spine. |
| WT-3 | W1, T3 | Reconciliation job or periodic audit between ledgers; alert on divergence. |

---

## Traceability

| Strategic action | Typical owner | Evidence |
|------------------|---------------|----------|
| SO-1 / WO-3 | Engineering | CI + router tests |
| SO-2 / WO-1 | Engineering + ops | [P0_PAPER_IB_VERIFICATION.md](../runbooks/P0_PAPER_IB_VERIFICATION.md) |
| ST-2 | Security | [SECURITY_REMEDIATION.md](../runbooks/SECURITY_REMEDIATION.md) |
| WT-2 | Ops | [PHASE3_READINESS.md](../runbooks/PHASE3_READINESS.md), risk RISK-004 / RISK-005 |

Update this file when SWOT items move from hypothesis to **closed** or **superseded** (note date in a one-line changelog at bottom).

---

**Changelog**

- 2026-04-09 — Initial TOWS mapping from integrated roadmap + master audit.
