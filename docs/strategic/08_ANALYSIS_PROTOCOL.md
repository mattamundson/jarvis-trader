# Analysis protocol

**Purpose:** Scoped passes to understand the repo **without** reading ~90k files (dependencies, screenshots, vendored tooling).  
**Origin:** Passes A–D from [INTEGRATED_ROADMAP_2026-04.md §3](../plans/INTEGRATED_ROADMAP_2026-04.md).

---

## Scope exclusions (always)

Ignore for “line count” or file inventory unless the task explicitly says otherwise:

- `node_modules/`, `dashboard/.next/`, `engine/.venv/`, `__pycache__/`
- Binary assets: `discord-charts/`, large PNG/PDF dumps, session screenshots
- Vendored skills: `.claude/skills/gstack/` (unless working on gstack itself)
- Unrelated trees: `PaperClip/` (unless task says jarvis-trader + PaperClip)
- **Greenfield / jarvis-v2** — out of scope unless explicitly named

**Product source roots (default):** `engine/` (excluding `.venv`), `dashboard/` (excluding `node_modules` / `.next`), `docs/runbooks/`, `infrastructure/` when touching deploy.

---

## Pass A — API, safety, signals

| Target | Path | Deliverable |
|--------|------|-------------|
| HTTP surface | [engine/routers/](../../engine/routers/), [engine/main.py](../../engine/main.py) | Table: prefix → router file → primary responsibility |
| Safety | [engine/risk/safety_layer.py](../../engine/risk/safety_layer.py), [engine/routers/safety_router.py](../../engine/routers/safety_router.py) | List of checks + test file pointers |
| Signals / backtest | [engine/backtest/](../../engine/backtest/), especially [signals.py](../../engine/backtest/signals.py) | What is Tier 3; how WFE feeds decisions |

**Exit criteria:** You can draw [02_SYSTEM_MAP.md](02_SYSTEM_MAP.md) trust boundary from memory.

---

## Pass B — Dashboard ↔ engine

| Target | Path | Deliverable |
|--------|------|-------------|
| API client | [dashboard/lib/api.ts](../../dashboard/lib/api.ts) | Every exported caller or pattern |
| Pages | [dashboard/app/](../../dashboard/app/) | Map route → engine endpoints used |
| Hooks | [dashboard/hooks/](../../dashboard/hooks/) | WebSocket + polling behaviors |

**Exit criteria:** List of top 15 engine URLs the dashboard calls; gaps become P3-1 tasks in [07_EXECUTION_SPINE.md](07_EXECUTION_SPINE.md).

---

## Pass C — Pipeline, markets, learning

| Target | Path | Deliverable |
|--------|------|-------------|
| Pipeline | [engine/agents/pipeline.py](../../engine/agents/pipeline.py), [engine/agents/](../../engine/agents/) | Stage diagram + external I/O |
| Markets | [engine/markets/](../../engine/markets/) | Module list vs [03_CAPABILITY_MATRIX.md](03_CAPABILITY_MATRIX.md) |
| Learning | [engine/learning/](../../engine/learning/) | What is real vs stub |

**Exit criteria:** Updated capability matrix rows if maturity changed.

---

## Pass D — Operations

| Target | Path | Deliverable |
|--------|------|-------------|
| Runbooks | [docs/runbooks/](../runbooks/) | Which book applies to today’s incident |
| Env / scripts | `engine/.env.example`, [restart_engine.ps1](../../restart_engine.ps1), [docs/troubleshooting.md](../troubleshooting.md) | Single-machine truth |
| IB / brokers | [docs/runbooks/IB_CONNECTOR_OVERVIEW.md](../runbooks/IB_CONNECTOR_OVERVIEW.md), execution adapters | Connection + reconnect story |

**Exit criteria:** Operator can restart engine and verify paper path without reading source.

---

## Cadence

| When | Action |
|------|--------|
| **Monthly** | Refresh [METRICS_SNAPSHOT.json](METRICS_SNAPSHOT.json) via [scripts/strategic_snapshot.py](../../scripts/strategic_snapshot.py); spot-check one pass (rotate A→D). |
| **Quarterly** | Re-run SWOT/TOWS in [04_SWOT_AND_STRATEGY.md](04_SWOT_AND_STRATEGY.md); update [05_RISK_REGISTER.md](05_RISK_REGISTER.md) Status column. |
| **Pre–Phase 3** | Full A+B+C+D with evidence attachments; reconcile [MASTER audit §20](../reports/MASTER_PROJECT_AUDIT_2026-04-04.md) gates. |

---

## Paste block for a scoped agent chat

```
Project: jarvis-trader only.

Pass: [A | B | C | D] — see docs/strategic/08_ANALYSIS_PROTOCOL.md

Constraints:
- Paper mode; LIVE_TRADING_ENABLED = False; no safety_layer kill logic edits without Tier 3.
- Canonical signals: engine/backtest/signals.py — Tier 3 for param changes.
- Approved paper: MES 1h, MGC 1h per .claude/imports/validated-instruments.md (MCL/MNQ halted, M2K rejected).

Deliverable: [one table / diagram / endpoint list — specify]

Exclusions: node_modules, .venv, discord-charts, jarvis-v2.
```

---

## Changelog

- 2026-04-09 — Initial protocol from integrated roadmap §3 + cadence.
