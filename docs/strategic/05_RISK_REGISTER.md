# Risk register

**Audience:** Engineering, ops, security.  
**Convention:** Each risk has a stable **RISK-xxx** ID. Closing or superseding a risk appends a row to the **Changelog** (bottom).  
**Source reconciliation:** Derived from [MASTER_PROJECT_AUDIT_2026-04-04 §8, §16–18, §20](../reports/MASTER_PROJECT_AUDIT_2026-04-04.md). **Status** reflects “as of strategic suite creation (2026-04-09)” — **verify** in codebase before treating as green.

---

## Register

| ID | Category | Risk | Likelihood | Impact | Detection | Mitigation / owner | Status |
|----|----------|------|------------|--------|-----------|-------------------|--------|
| RISK-001 | Security | API keys or secrets in git history or clones | High if unrotated | Critical | Secret scan, audit logs | Rotate keys; history scrub per [SECURITY_REMEDIATION.md](../runbooks/SECURITY_REMEDIATION.md) | **Open — verify** |
| RISK-002 | Security | Keys or PII in logs, transcripts, or Discord | Med | High | Log review, grep CI | Sanitization, [test_log_sanitizer](../../engine/tests/test_log_sanitizer.py), policy | **Open — verify** |
| RISK-003 | Safety | Kill switch / circuit state not persisted across engine restart | Med | High | Restart drill | Persist state (audit cited missing `system_state`); tests for restore | **Open — verify** |
| RISK-004 | Ops | IB Gateway disconnect without auto-reconnect during validation | Med | High | Uptime monitor, alerts | Reconnect logic + runbook; [P0_PAPER_IB_VERIFICATION.md](../runbooks/P0_PAPER_IB_VERIFICATION.md) | **Open — verify** |
| RISK-005 | Data | No automated DB / SQLite backup | Med | High | Backup job absent | Scheduled backup + restore drill; see audit US-1102 | **Open — verify** |
| RISK-006 | Data | Dual ledger: JSONL / SQLite / paper_runner vs engine portfolio diverge | Med | High | Reconciliation script, widget cross-check | Single SoT decision + sync path (roadmap P0) | **Open** |
| RISK-007 | Research | Continued tuning on MES/MGC against validation policy | Med | Med | Instrument allowlist, WFE artifacts | Gates in [06_VALIDATION_GATES.md](06_VALIDATION_GATES.md) | **Open — process** |
| RISK-008 | Engineering | `main.py` monolith changes cause unintended router/middleware regressions | Med | High | CI pytest + smoke routes | Incremental extract; [test_routes_wired](../../engine/tests/test_routes_wired.py) | **Open** |
| RISK-009 | Engineering | Unmounted or dead routers clutter API surface | Low | Med | Route inventory vs mounts | Audit delete or mount; audit §16 | **Open — verify** |
| RISK-010 | Quality | Intermittent async test / CI flakiness masks real bugs | Med | Med | CI history | Stabilize fixtures; audit §18 T8 | **Open — verify** |
| RISK-011 | Financial | PnL divergence across SQLite vs in-memory (audit B9) | Med | High | Compare reports | Single calculation path; tests | **Open — verify** |
| RISK-012 | Product | Phase 3 pressure before 30-day validation complete | Med | Critical | Phase checklist | [PHASE3_READINESS.md](../runbooks/PHASE3_READINESS.md), [PHASE3_TODOS](../backlog/PHASE3_TODOS.md) | **Process** |
| RISK-013 | Vendor | LLM billing outage blocks pipeline (not safety) | Med | Med | Provider status | Degraded analysis UX; caching (no safety LLM) | **Partial** |
| RISK-014 | Compliance / ops | Live port or flag flipped without Tier 3 | Low | Critical | Config review, grep CI | `LIVE_TRADING_ENABLED` + code review policy | **Controlled** |

---

## Likelihood / impact scale (project-local)

| Level | Likelihood | Impact |
|-------|------------|--------|
| Low | Rare in normal ops | Limited blast radius |
| Med | Observed or plausible quarterly | Material P&L, trust, or downtime |
| High | Observed or imminent without mitigation | Capital, safety bypass, or sustained outage |

---

## Mapping to master audit artifacts

| Audit reference | RISK IDs |
|-----------------|----------|
| T1 Security / W2 keys in history | RISK-001, RISK-002 |
| T2 / W4 IB fragility | RISK-004 |
| T3 no backup | RISK-005 |
| T5 dual storage / B9 PnL | RISK-006, RISK-011 |
| W5 kill switch not persisted | RISK-003 |
| W1 main.py / T6 refactor | RISK-008 |
| T4 MES overfit | RISK-007 |
| T8 async tests | RISK-010 |

---

## Review cadence

- **Weekly (operator):** Scan RISK-003, RISK-004, RISK-006 during paper week.
- **Monthly:** Full table review; update Status column with evidence (PR link, test name).
- **Before Phase 3:** RISK-001, RISK-003, RISK-004, RISK-005, RISK-012 must be **Closed** or **Accepted** with named sign-off.

---

## Changelog

- 2026-04-09 — Initial register from master audit; statuses marked verify pending engineering confirmation.
