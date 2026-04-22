---
repo: KaustubhPatange/polymarket-trade-engine
url: https://github.com/KaustubhPatange/polymarket-trade-engine
stars: 107
language: TypeScript
license: MIT
archived: false
pushed_at: 2026-04-19
analyzed_at: 2026-04-19
recommendation: partial-integrate
surfaces_with_value: [engine-code]
---

# KaustubhPatange/polymarket-trade-engine

## Core value proposition

TypeScript trade execution engine for Polymarket binary prediction markets.
Handles 5/15-minute UP/DOWN markets on thin CLOB liquidity (~150K USDC/side).
Patterns around event-driven order lifecycle and state transitions are
venue-agnostic and reusable.

## License

**MIT** — free to port with attribution.

## 9-surface grid

| # | Surface | Classification | Finding |
|---|---|---|---|
| 1 | Engine code | partial-integrate | Event-driven callback chain (order → filled/expired → callback) aligns with `engine/execution/ib_order_manager.py` pattern. State lifecycle (INIT→RUNNING→STOPPING→DONE) reusable for backtest harness. Cleanup-return pattern applicable to strategy teardown |
| 2 | Project rules | no-fit | — |
| 3 | Skills | no-fit | — |
| 4 | Slash commands | no-fit | — |
| 5 | Subagents | no-fit | — |
| 6 | Docs | no-fit | — |
| 7 | Dev tooling | no-fit | Node/TS stack; pnpm OK but not worth a port |
| 8 | Dashboard | no-fit | Polymarket-specific order-book UI |
| 9 | Ops | no-fit | — |

## Not-fit patterns (explicit)

- Order book subscriptions (CLOB-specific)
- Polymarket CLOB token mechanics
- Sub-minute slot timing (binary markets only)
- Polymarket API clients

These are all **venue-specific**. Don't attempt to reuse.

## Integration plan

Reference-only (ideas, not code copy):

1. **Lifecycle states** (S, 2h). Audit `engine/execution/ib_order_manager.py`
   and `engine/backtest/*` for places where an explicit
   INIT→RUNNING→STOPPING→DONE state machine would clarify teardown. Small
   refactor if it reduces reconnect/teardown bugs.
2. **Cleanup-return pattern** (S, 1h). For any strategy registered with
   the pipeline, ensure the registration returns a teardown callable
   (React-style `useEffect` cleanup). Simplifies hot-reload testing.

## Red flags

- **Different venue paradigm**. Prediction markets ≠ futures. Easy to
  over-generalize — treat as inspiration only.
- **Venue regulatory risk**: Polymarket is CFTC-scrutinized. Any wiring
  of prediction-market data into jarvis-trader requires legal review.
- **Active maintenance** (pushed 2026-04-19): good, but the surface area
  worth porting is tiny.

## Effort

Reference-only: **S (3h total)**. No code copy planned.
