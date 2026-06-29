# Executive brief

**Audience:** Principal / operator (you).  
**Refresh:** When phase changes, instrument policy changes, or monthly at minimum.  
**Canon:** Instrument numbers and gates defer to [.claude/imports/validated-instruments.md](../../.claude/imports/validated-instruments.md) and [JARVIS_TRADER_UNIFIED_CANON.md](../JARVIS_TRADER_UNIFIED_CANON.md).

---

## 1. What this system is

JARVIS TRADER is a **paper-first** AI-assisted futures and options platform: **FastAPI engine** (8010) + **Next.js dashboard** (3010), **5-stage LLM pipeline** (10 agents), **hardcoded Python safety layer** (not LLM-driven), **human approval** required for order flow.

---

## 2. Phase and mode

| Dimension | State |
|-----------|--------|
| **Phase** | Hardening / paper trading validation (pre–Phase 3 live) |
| **`LIVE_TRADING_ENABLED`** | `False` until explicit Tier 3 approval |
| **`REQUIRE_HUMAN_APPROVAL`** | `True` — non-negotiable |
| **Approved paper symbols** | **MES 1h** (p_edge 0.75), **MGC 1h** (p_edge 0.6842) — active paper since Tier-3 flip 2026-05-24 (gates per validated-instruments) |
| **Halted (`DO_NOT_TRADE`)** | **MCL 1h** (WFE 0.82), **MNQ 1h** (WFE 0.57) — strategy hypotheses exhausted / fail gate v2 |
| **Rejected** | **M2K 1h** — SMA/ORB/Donchian all FAIL 2026-05-24 |

---

## 3. Top five risks (actionable)

These align with [05_RISK_REGISTER.md](05_RISK_REGISTER.md). Verify mitigations in CI and runbooks; do not treat this list as exhaustive.

1. **Secrets exposure** — Historical or accidental API key leakage; unauthorized LLM or broker usage. *Pointer:* [docs/runbooks/SECURITY_REMEDIATION.md](../runbooks/SECURITY_REMEDIATION.md).
2. **Operational fragility** — IB Gateway / engine restart / notification chains failing silently or requiring elevation. *Pointer:* [docs/troubleshooting.md](../troubleshooting.md), [docs/engine-restart-checklist.md](../engine-restart-checklist.md).
3. **Dual paper truth** — Engine SQLite / portfolio APIs vs `paper_runner` or JSON artifacts diverging. *Pointer:* [PAPER_SOURCE_OF_TRUTH.md](../runbooks/PAPER_SOURCE_OF_TRUTH.md), [INTEGRATED_ROADMAP §5](../plans/INTEGRATED_ROADMAP_2026-04.md).
4. **Strategy overfit on wrong instrument** — Tuning MES/MGC or expanding symbols without WFE discipline. *Pointer:* [06_VALIDATION_GATES.md](06_VALIDATION_GATES.md).
5. **Complexity regression** — Large router surface + `main.py` orchestration without contract tests on critical paths. *Pointer:* Master audit §16–17; [07_EXECUTION_SPINE.md](07_EXECUTION_SPINE.md) P3.

---

## 4. Top five leverage bets

1. **Single golden paper path** — One documented E2E: data → pipeline → approval → logged outcome → dashboard widget; eliminate ambiguous “which ledger is truth.”
2. **Health and safety contracts** — Stable JSON for `/health`, `/safety/*` for automation and dashboard degraded modes (no LLM in safety decisions).
3. **Contract tests** — Top N `fetchEngine` / `postEngine` paths vs engine responses (dashboard ↔ engine).
4. **Cost / latency telemetry** — Pipeline profiling + billing visibility; optional degraded analysis when LLM unavailable (analysis only, never safety).
5. **Canon + strategic index as entry point** — Every session and new contributor starts from [README.md](README.md) + [Unified Canon](../JARVIS_TRADER_UNIFIED_CANON.md).

---

## 5. Explicit non-goals (this quarter)

- Enabling **live** trading or **`LIVE_TRADING_ENABLED=True`** without Phase 3 runbook completion and Tier 3 sign-off.
- Using **LLM output** to override or replace **safety_layer** or kill-switch logic.
- **Production tuning** of STC/regime parameters in [engine/backtest/signals.py](../../engine/backtest/signals.py) without Tier 3 approval.
- Treating **in-sample** backtest excellence on **MES** as justification to treat it as **production-grade** while WFE remains poor (paper-only per canon).

---

## 6. Where to go next

| Need | Doc |
|------|-----|
| Architecture + trust boundaries | [02_SYSTEM_MAP.md](02_SYSTEM_MAP.md) |
| Backlog and DoD | [07_EXECUTION_SPINE.md](07_EXECUTION_SPINE.md) |
| Full risk table | [05_RISK_REGISTER.md](05_RISK_REGISTER.md) |
| How to re-audit the repo safely | [08_ANALYSIS_PROTOCOL.md](08_ANALYSIS_PROTOCOL.md) |
