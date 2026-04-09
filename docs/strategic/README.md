# JARVIS TRADER — Strategic command center

**Purpose:** Thin navigation layer over canon, audits, and runbooks. Each numbered doc has one job. Prefer **links** over copy-pasted metrics that rot.

**Last indexed:** 2026-04-09

---

## Reading paths

### 60 seconds

Read [01_EXECUTIVE_BRIEF.md](01_EXECUTIVE_BRIEF.md) — phase, mode, top risks, top bets, non-goals.

### 15 minutes (onboarding / Monday stand-up)

1. [01_EXECUTIVE_BRIEF.md](01_EXECUTIVE_BRIEF.md)
2. [02_SYSTEM_MAP.md](02_SYSTEM_MAP.md) — trust boundaries (LLM vs Python)
3. [07_EXECUTION_SPINE.md](07_EXECUTION_SPINE.md) — P0–P4 and Definition of Done

### Deep dive (architecture + risk + validation)

| Order | Document |
|-------|----------|
| 1 | [02_SYSTEM_MAP.md](02_SYSTEM_MAP.md) |
| 2 | [03_CAPABILITY_MATRIX.md](03_CAPABILITY_MATRIX.md) |
| 3 | [06_VALIDATION_GATES.md](06_VALIDATION_GATES.md) |
| 4 | [05_RISK_REGISTER.md](05_RISK_REGISTER.md) |
| 5 | [04_SWOT_AND_STRATEGY.md](04_SWOT_AND_STRATEGY.md) |
| 6 | [08_ANALYSIS_PROTOCOL.md](08_ANALYSIS_PROTOCOL.md) |

Then cross-check against [Unified Canon](../JARVIS_TRADER_UNIFIED_CANON.md) and the dated [Master project audit](../reports/MASTER_PROJECT_AUDIT_2026-04-04.md).

---

## Tier-1 references (truth hierarchy)

| Artifact | Role |
|----------|------|
| [JARVIS_TRADER_UNIFIED_CANON.md](../JARVIS_TRADER_UNIFIED_CANON.md) | Canon policy, narrative, research truth ledger |
| [.claude/imports/validated-instruments.md](../../.claude/imports/validated-instruments.md) | Approved / halted symbols and WFE gates |
| [CLAUDE.md](../../CLAUDE.md) | Session rules, safety non-negotiables, commands |
| [.claude/rules/safety.md](../../.claude/rules/safety.md) | Full safety invariants |

---

## Operational snapshots and plans

| Artifact | Role |
|----------|------|
| [CURRENT_STATE.md](../CURRENT_STATE.md) | Ports, env, instrument table snapshot |
| [INTEGRATED_ROADMAP_2026-04.md](../plans/INTEGRATED_ROADMAP_2026-04.md) | P0–P4 priorities, SWOT, success criteria |
| [MASTER_PROJECT_AUDIT_2026-04-04.md](../reports/MASTER_PROJECT_AUDIT_2026-04-04.md) | 20-section evidence audit (archive + depth) |

---

## Runbooks (execute, don’t reread strategy)

| When | Runbook |
|------|---------|
| Paper + IB verification | [P0_PAPER_IB_VERIFICATION.md](../runbooks/P0_PAPER_IB_VERIFICATION.md) |
| Phase 3 gates | [PHASE3_READINESS.md](../runbooks/PHASE3_READINESS.md) |
| Key rotation / secrets | [SECURITY_REMEDIATION.md](../runbooks/SECURITY_REMEDIATION.md) + [API_KEY_ROTATION.md](../runbooks/API_KEY_ROTATION.md) |
| Daily ops | [daily_ops.md](../runbooks/daily_ops.md) |
| Engine restart / incidents | [docs/troubleshooting.md](../troubleshooting.md) (repo root: `docs/troubleshooting.md`) |
| Security operator checklist | [SECURITY_OPERATOR_CHECKLIST.md](../runbooks/SECURITY_OPERATOR_CHECKLIST.md) |
| Paper source of truth | [PAPER_SOURCE_OF_TRUTH.md](../runbooks/PAPER_SOURCE_OF_TRUTH.md) |
| IB reconnect + health | [IB_RECONNECT_AND_HEALTH.md](../runbooks/IB_RECONNECT_AND_HEALTH.md) |
| Health / safety JSON contract | [HEALTH_API_CONTRACT.md](../runbooks/HEALTH_API_CONTRACT.md) |
| SQLite backup (nightly + on-demand) | [SQLITE_BACKUP.md](../runbooks/SQLITE_BACKUP.md) |

---

## Machine-readable metrics

Optional snapshot (regenerate after major refactors): [METRICS_SNAPSHOT.json](METRICS_SNAPSHOT.json) — see [scripts/strategic_snapshot.py](../../scripts/strategic_snapshot.py).

---

## Document map (this folder)

| File | One-line job |
|------|----------------|
| [01_EXECUTIVE_BRIEF.md](01_EXECUTIVE_BRIEF.md) | Posture and priorities |
| [02_SYSTEM_MAP.md](02_SYSTEM_MAP.md) | Architecture + trust zone diagrams |
| [03_CAPABILITY_MATRIX.md](03_CAPABILITY_MATRIX.md) | Maturity by capability |
| [04_SWOT_AND_STRATEGY.md](04_SWOT_AND_STRATEGY.md) | SWOT + TOWS actions |
| [05_RISK_REGISTER.md](05_RISK_REGISTER.md) | ID’d risks, detection, mitigation |
| [06_VALIDATION_GATES.md](06_VALIDATION_GATES.md) | WFE, Tier-3 files, research gates |
| [07_EXECUTION_SPINE.md](07_EXECUTION_SPINE.md) | Single backlog narrative |
| [08_ANALYSIS_PROTOCOL.md](08_ANALYSIS_PROTOCOL.md) | Scoped analysis passes A–D |
