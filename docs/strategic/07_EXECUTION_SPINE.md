# Execution spine

**Purpose:** One backlog narrative merging [INTEGRATED_ROADMAP_2026-04.md §2–3, §8](../plans/INTEGRATED_ROADMAP_2026-04.md) with Phase 3 artifacts.  
**Priority rule:** P0 > P1 > P2 > P3 > P4. P4 items require **Tier 3** for anything touching canonical signals or live flags.

---

## Horizon map

| Horizon | Goal |
|---------|------|
| **Now** | Boring paper ops: IB path + single paper truth + no silent health failures |
| **Next** | Contract tests + stable health JSON + cost visibility |
| **Later** | Learning loop value + optional rate-limit productization |
| **Gated** | New symbols / STC changes / live — see [06_VALIDATION_GATES.md](06_VALIDATION_GATES.md) |

---

## P0 — Operational (this week / blocking paper trust)

| ID | Task | Definition of Done (DoD) | Evidence |
|----|------|---------------------------|----------|
| P0-1 | IB Gateway paper path E2E | Connect → trade or sim path → positions visible in engine + dashboard consistent with broker | [P0_PAPER_IB_VERIFICATION.md](../runbooks/P0_PAPER_IB_VERIFICATION.md) completed once; notes in session log |
| P0-2 | Single source of truth for paper | Documented default SoT; dashboard widgets use it; optional `paper_runner` → engine sync env path tested or explicitly deprecated | ADR or runbook section + one reconciliation check |

**Related risks:** [RISK-004](05_RISK_REGISTER.md), [RISK-006](05_RISK_REGISTER.md). **SoT doc:** [PAPER_SOURCE_OF_TRUTH.md](../runbooks/PAPER_SOURCE_OF_TRUTH.md).

---

## P1 — Reliability and hygiene

| ID | Task | DoD | Evidence |
|----|------|-----|------------|
| P1-1 | Git/workspace health | Clean `git status` on main worktree; remotes correct; no silent CI drift | PR or ops note |
| P1-2 | Health contracts | `/health`, `/health/full`, `/safety/status`, `/safety/circuit-breakers` return stable shapes documented for dashboard | Sample JSON in runbook or OpenAPI; dashboard handles 503 gracefully |

**Related risks:** RISK-008 (if changing startup), RISK-003.

---

## P2 — Agents and analysis surface

| ID | Task | DoD | Evidence |
|----|------|-----|------------|
| P2-1 | Anthropic billing active | Credits available; one full pipeline run completes | Log or `/profiling` / cost tracker |
| P2-2 | Cost / latency awareness | Visible pipeline cost or duration; optional degraded mode for **analysis only** when LLM down | Metrics or UI banner; no safety LLM |

---

## P3 — Quality and test debt

| ID | Task | DoD | Evidence |
|----|------|-----|------------|
| P3-1 | Critical-path contract tests | Top N engine routes used by dashboard covered | Tests in `engine/tests/` + dashboard e2e if present |
| P3-2 | Rate limiting (if required) | Documented limits; consistent middleware; tests | Align with [test_rate_limiting](../../engine/tests/test_rate_limiting.py) |

**Related risks:** RISK-010, RISK-008.

---

## P4 — Research (gated)

| ID | Task | DoD | Evidence |
|----|------|-----|----------|
| P4-1 | MES | Research only; no production tuning | WFE artifact; no allowlist change |
| P4-2 | MGC | Halted; research only | Same |
| P4-3 | New symbols / TF | WFE + explicit approval before `signals.py` / production config | Checklist in [06_VALIDATION_GATES.md](06_VALIDATION_GATES.md) |

---

## Phase 3 alignment

| Artifact | Role |
|----------|------|
| [PHASE3_READINESS.md](../runbooks/PHASE3_READINESS.md) | Gate checklist before live |
| [PHASE3_TODOS.md](../backlog/PHASE3_TODOS.md) | Tracked items |
| [MASTER_PROJECT_AUDIT_2026-04-04 §20](../reports/MASTER_PROJECT_AUDIT_2026-04-04.md) | Historical gate table — reconcile with current engine before relying on grades |

**DoD for “Phase 3 conversation” (not same as flipping live):** P0 complete; RISK-001/003/004/005 addressed or explicitly accepted; 30-day validation plan running on **approved** symbols only.

---

## Success criteria (from integrated roadmap)

**Short term**

- [ ] P0-1 checklist executed once — runbook [P0_PAPER_IB_VERIFICATION.md](../runbooks/P0_PAPER_IB_VERIFICATION.md); evidence template [p0-paper-ib-verification-template.md](../session-logs/p0-paper-ib-verification-template.md); helper `engine/scripts/verify_p0_paper_ib.py` (default IB TCP check port **4002** when `CHECK_IB_PORT=1`)  
- [ ] Billing active; at least one full pipeline run recorded  
- [x] Paper state story documented — [PAPER_SOURCE_OF_TRUTH.md](../runbooks/PAPER_SOURCE_OF_TRUTH.md) (default DB path + backup link)

**Medium term**

- [x] Contract tests for top dashboard→engine paths — `engine/tests/test_routes_wired.py` (`critical_routes`), `engine/tests/test_api_contract_minimal.py` (`/health`, `/safety/*`), `engine/tests/test_market_data_waterfall.py`, `engine/tests/test_pipeline_alert_cooldown.py`, `engine/tests/test_paper_ledger_pnl_consistency.py`, `engine/tests/test_ib_reconnect_contract.py`  
- [ ] No critical health/safety 500s on cold start with minimal env  

**Research**

- [ ] New symbol/timeframe: WFE artifact + approval before canonical signal/config changes  

---

## Changelog

- 2026-04-09 — Initial spine from integrated roadmap + risk cross-links.
