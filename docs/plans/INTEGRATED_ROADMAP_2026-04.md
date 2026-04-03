# JARVIS TRADER — Integrated roadmap (2026-04)

This document merges the **Phase 6 / session-log follow-up plan** (2026-04-02), **implementation outcomes** from that sprint, and **expanded priorities** (operations, quality, research gates, SWOT, and how to scope future work).

---

## 1. Snapshot: what the 2026-04-02 plan already covered

| Track | Intent | Post-sprint status (high level) |
|--------|--------|----------------------------------|
| Billing | Anthropic credits for pipeline agents | **External** — console billing only |
| Command center | Iron Man HUD, live ops view | **Improved** — fonts, live WFE from `/backtest/paper-status`, existing engine hooks |
| Paper integration | One truth for paper vs JSON | **Partial** — `/portfolio/paper/*`, `/portfolio/history/trades`, optional `paper_runner` → engine POST when `JARVIS_ENGINE_URL` + key set |
| Test / auth quality | e2e mocks, auth tests | **Addressed** — global API key middleware, safety routes restored, auth tests use `settings.API_KEY`, pipeline mock conflict removed |
| SPY WFE | Re-run after optimizer fix | **Sample run done** — narrow window; full canonical re-run still optional |

Canonical references: [SESSION_LOG_2026-04-02.md](../session-logs/SESSION_LOG_2026-04-02.md), [CLAUDE.md](../../CLAUDE.md) (approved instruments, safety non-negotiables).

---

## 2. Next tasks — prioritized (jarvis-trader–specific)

Order is **leverage × risk reduction** for paper phase.

### P0 — Operational

1. **IB Gateway paper path end-to-end**  
   Fills, positions, and dashboard truth aligned with broker state; eliminate ambiguity vs standalone `paper_runner` JSON when both exist.

2. **Single source of truth for paper**  
   Extend the `paper_runner` → engine sync path (env-based) into default ops where appropriate, or document “when to use which” and ensure dashboard widgets read the chosen source consistently.

**Actionable checklist:** [docs/runbooks/P0_PAPER_IB_VERIFICATION.md](../runbooks/P0_PAPER_IB_VERIFICATION.md)

### P1 — Reliability & repo hygiene

3. **Git / local workspace health**  
   If `git status` / `HEAD` / remotes were flaky, restore so manifests, CI, and local diffs match reality (no silent drift).

4. **Health contracts**  
   Fewer opaque 500s; stable shapes for `/health`, `/health/full`, `/safety/status`, `/safety/circuit-breakers` for dashboards and scripts.

### P2 — Agents & analysis surface

5. **Anthropic billing / credits**  
   Unblocks the 5-stage LLM pipeline; no substitute in code.

6. **Cost / latency awareness**  
   Optional: caching, batching, or “degraded mode” UX when LLM unavailable (without touching safety decisions).

### P3 — Quality & test debt

7. **Critical-path tests**  
   Contract tests for `fetchEngine` / proxy routes vs engine; order/safety paths; portfolio paper endpoints.

8. **Rate limiting**  
   If product requires it, wire `slowapi` (or equivalent) consistently with documented limits (session notes referenced rate-limit tests).

### P4 — Research (gated — Tier 3 / approval)

9. **MES** — DO NOT TRADE / research paused; any work is **research only**, not production tuning.  
10. **MGC** — HALTED; same gate.  
11. **New symbols / timeframes** — disciplined walk-forward + WFE before approval; align with [engine/backtest/signals.py](../../engine/backtest/signals.py) change control.

**Production tuning guardrail:** until Tier 3 explicitly changes it, treat **`engine/backtest/signals.py`** (STC/regime) and **`engine/config.py`** / `TradingConfig` as **canonical** — improve execution, sizing, logging, regime *reporting*, learning loop *recommendations*, not blind STC rewrites on unapproved symbols.

---

## 3. Comprehensive “whole project” analysis — how to do it without boiling the ocean

| Pass | Scope | Typical depth |
|------|--------|----------------|
| A | `engine/routers/` + `engine/risk/` + `engine/backtest/` | API + safety + signals/backtest |
| B | `dashboard/lib/api.ts` + `dashboard/app/**` | Every `fetchEngine` / `postEngine` path vs engine |
| C | `engine/learning/`, `engine/markets/`, `engine/agents/pipeline.py` | Learning + multi-market + pipeline only |
| D | Ops: PM2, env, IB, data providers | Runbooks + single-machine truth |

**Recommendation:** one pass per milestone or one new chat per pass with a fixed goal (“map all paper-related endpoints,” “list all safety touchpoints,” etc.). Ignore **Greenfield / jarvis-v2** unless explicitly in scope.

---

## 4. Should we “improve trading strategies” in code?

**Yes, with guardrails:**

- **Approved for paper:** MCL 1h, MNQ 1h — improvements that **do not** silently change STC/regime thresholds might include execution, position sizing *within* existing rules, telemetry, and learning feedback **that never overrides** [engine/risk/safety_layer.py](../../engine/risk/safety_layer.py).
- **Canonical parameters:** changes to STC/regime logic in [engine/backtest/signals.py](../../engine/backtest/signals.py) = **Tier 3** approval.
- **MES / MGC:** research or halt — not “production tuning.”

---

## 5. Weaknesses (honest, high level)

| Area | Risk |
|------|------|
| Two paper worlds | `paper_runner` disk JSON vs engine SQLite / portfolio APIs can diverge if sync is off or partial. |
| LLM surface | Cost, latency, billing dependency; quality drops when API is down (safety correctly stays non-LLM). |
| Complexity | Many routers and dashboard pages → regression risk without tests on critical paths. |
| Data | Yahoo / free tiers / rate limits affect `paper_runner` and research reproducibility. |
| Validated universe | Only MCL/MNQ cleared for paper → easy to overfit or “improve” the wrong instrument. |

---

## 6. SWOT (jarvis-trader–centric)

### Strengths

- Safety architecture: kill switch, hard limits, human approval, paper mode; safety layer is hardcoded Python, not LLM-driven.
- Multi-market orchestrator and learning modules — potential to compound edge from structured logs and feedback.
- Clear separation: engine vs dashboard; `fetchEngine` / `postEngine` pattern.
- Documentation: session logs, runbooks, WFE / instrument gates in CLAUDE.md.

### Weaknesses

- Integration gaps (paper runner vs engine; optional services when keys missing).
- Test/CI debt in non-critical areas; local git health can drift.
- Large strategy *surface area* vs small *validated* surface (MCL/MNQ).
- Operational dependencies: IB, data vendors, LLM provider.

### Opportunities

- Unify paper state for dashboard + alerts (one ledger).
- Learning loop: systematic recommendations from paper outcomes (never safety overrides without Tier 3).
- Hardening: stable health contracts; contract tests for dashboard ↔ engine.
- Research pipeline: WFE + approval workflow before new symbols go live.

### Threats

- Pressure to go live before paper + IB + stats are boringly stable.
- Secrets in logs/transcripts (already burned once — stay disciplined).
- Regime change — parameters validated on past windows can degrade.
- Vendor/API changes (data, broker, models).

---

## 7. New conversation vs stay in this thread

| Stay here | Start a new chat |
|-----------|------------------|
| Single file, single bug, one clarification | Full-repo or multi-module strategy review |
| Small follow-up on a merged PR | SWOT → **concrete backlog** with file-level tasks |
| Tweak one endpoint or widget | Deep dive: `signals.py` + `paper_config` + WFE results together |
| | Scoped “analysis pass” A/B/C/D above as a dedicated effort |

### Paste block for the next chat (copy as-is or trim)

```
Project: jarvis-trader only (ignore Greenfield / jarvis-v2).

Goal: [e.g. scoped engine analysis pass A | IB paper E2E | unified paper ledger]

Constraints:
- Paper mode; LIVE_TRADING_ENABLED = False; no edits to safety_layer kill logic without Tier 3.
- Canonical signals: engine/backtest/signals.py — Tier 3 for param changes.
- Approved paper: MCL 1h, MNQ 1h. MES/MGC = research/halt only.

Pointers:
- docs/session-logs/SESSION_LOG_2026-04-02.md
- docs/plans/INTEGRATED_ROADMAP_2026-04.md
- engine/backtest/signals.py, engine/config.py, engine/risk/safety_layer.py
- CLAUDE.md approved instruments table

Depth: [quick scan | deep dive on listed files only]
```

---

## 8. Success criteria (for “this plan is done”)

Short term:

- [ ] IB paper path verified once with [P0 paper + IB checklist](../runbooks/P0_PAPER_IB_VERIFICATION.md) (connect → position → dashboard).
- [ ] Anthropic billing active; at least one full pipeline run recorded.
- [ ] Paper state story documented: runner-only vs engine-sync vs IB.

Medium term:

- [ ] Contract tests for top 15 dashboard→engine paths.
- [ ] No critical health/safety 500s on cold start with minimal env.

Research (gated):

- [ ] Any new symbol/timeframe: WFE artifact + explicit approval before `signals.py` / production config changes.

---

*Integrated from session log 2026-04-02, follow-up implementation notes, and expanded backlog / SWOT. Update this file when priorities shift.*
