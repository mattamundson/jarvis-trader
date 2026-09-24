# JARVIS Rebuild Plan Set — v2.0 (2026-09-23)

> **Status: DESIGN ONLY.** Nothing in this plan set has been implemented, provisioned, purchased, or
> deployed. No credentials were read. No live-trading, risk, kill-switch, broker-routing, or symbol-gate
> change was made or proposed for immediate execution.
>
> These documents are **uncommitted** in the working tree. Commit / PR is a separate decision.

## Read in this order

| # | Document | What it answers |
|---|---|---|
| 1 | [`JARVIS_REBUILD_BLUEPRINT_v2.0.md`](./JARVIS_REBUILD_BLUEPRINT_v2.0.md) | What the system should be — verified ground truth, keep/rebuild/retire triage, the five invariants, 12 architecture layers, migration strategy, 9 phases with exit gates, cost model, risk register, anti-patterns, definition of done |
| 2 | [`JARVIS_REBUILD_DASHBOARD_SPEC_v2.0.md`](./JARVIS_REBUILD_DASHBOARD_SPEC_v2.0.md) | What the operator surface should be — 58 routes → 1 HUD + 13 surfaces, the seven UI laws, the provenance envelope, design system tokens, 14 page specs with data contracts, realtime/perf/a11y budgets, testing, migration with a redirect table |
| 3 | [`JARVIS_REBUILD_WORK_BREAKDOWN_v2.0.md`](./JARVIS_REBUILD_WORK_BREAKDOWN_v2.0.md) | How to get there — phases P0–P8 with task IDs, exact file paths, verification commands, exit gates, rollback, owner tags, execution order |
| 4 | [`JARVIS_REBUILD_DATA_INFRA_PROCUREMENT_v2.0.md`](./JARVIS_REBUILD_DATA_INFRA_PROCUREMENT_v2.0.md) | What to buy — vendor options with cost bands, priority order, what NOT to buy, owner actions, vendor checklist, spend gates |

## The thesis in five sentences

**Scope fence:** JARVIS is **futures + options + equities**. Commodities research is **amo-arbitrage's**
mandate; amo-arbitrage is referenced here only as the *planning pattern* to emulate, not as an asset-class
template.

**Single-operator mandate:** JARVIS is a **personal system with exactly one user — Amo.** No team, no org, no
product, no customers, and **no labor line in any cost model**. The build and upkeep are agent loops; the
only scarce input is Amo's own attention, and the plan optimizes for minimizing it.

1. JARVIS is **over-built and under-verified**: 85 API routers, 271 research modules and 58 dashboard routes
   sit on one consumer Windows box with 9.6 GB free disk, backed by SQLite.
2. The validation authority covers **1 of the 5 symbols actually trading** — SPY trades on a REJECTED
   verdict, QQQ/AAPL/TSLA trade with *no* verdict on file.
3. The rebuild is not "more features": it is **truth → validation → execution fidelity → breadth → polish**,
   in that order, with a gate between each.
4. Money buys exactly **one** thing here — **resolution (data)**. It does not buy conviction, and it does not
   buy the build, because the build is agent work in a single-operator system.
5. The operator surface collapses to **one screen that answers "am I safe to trade right now?"** with
   provenance on every number.

## Non-negotiable safety boundary (unchanged by this plan set)

- `LIVE_TRADING_ENABLED` stays `False`.
- `DO_NOT_TRADE_SYMBOLS = {MGC, MCL, MNQ, M2K}` — blocklist beats every carve-out, proven by test.
- Kill-switch thresholds, risk parameters, and `.env` runtime values are not touched.
- Safety decisions are pure Python, never LLM-mediated.
- Any change to risk / execution / config / kill-switch / symbol gates is a `[safety-review]` PR requiring
  Amo's explicit sign-off.
- The MES paper forward-evidence clock is **preserved, never reset** (task P3-6).

## Supersedes

- `docs/JARVIS_SOTA_PLAN.md` (2026-07-06) — a stabilization plan for the running system. Useful history;
  this plan set replaces it as the forward-looking source of truth.
- Relationship to `docs/plans/JARVIS_MASTER_IMPLEMENTATION_PLAN_v1.0.md`: that document governs *how work is
  proposed and merged* (MIP metadata, safety classes, verification rungs). This plan set governs *what the
  system should become*. They are complementary; where they conflict, the safety boundary wins and the MIP
  process governs execution.

## Immediate next actions (ranked)

1. **Answer the 8 open decisions** in blueprint §11 (D1–D8). Three block everything else: trunk (D7),
   trading-plane host (D1), store (D2).
2. **Owner actions A-1…A-8** in the procurement doc — GitHub billing and the IBKR entitlement review are
   the two that unblock the most.
3. **Start P0** (truth & hygiene) — it is fully agent-executable, reversible, and immediately valuable.
