# JARVIS Trader dashboard architecture decision

## Decision

Evolve the existing dashboard; do not start a second dashboard from scratch.

## Why

The existing Next.js dashboard is already a functioning product surface: it has the route structure, shared API/provenance helpers, live engine proxy, accessibility work, safety states, 217 unit tests before this change, and a healthy running instance on port 3010. A parallel rebuild would duplicate those contracts, split validation effort, and create a second source of truth while the trading engine remains the authoritative system.

The current problems are trust and correctness issues, not missing application foundations. The highest-value example was `realized_pnl`: `/pnl/truth` and `/portfolio/stats/summary` represent lifetime realized P&L, while `/portfolio/summary` represents the current-day component under the same field name. Rebuilding the UI would not solve that contract ambiguity.

## Operating model

1. Keep the current dashboard as the canonical shell and navigation.
2. Repair engine contracts with additive, explicitly scoped fields.
3. Update dashboard consumers to prefer explicit fields and retain backward-compatible fallbacks.
4. Add regression tests at both API and rendering-helper boundaries.
5. Rebuild only isolated surfaces when a measured product requirement cannot be met by the current shell; do not fork the entire application.

## First repair delivered

- Added `daily_realized_pnl` to `/portfolio/summary` while retaining `realized_pnl` as a compatibility alias.
- Added a dashboard resolver that prefers `daily_realized_pnl`, falls back to the legacy alias, and returns `null` instead of fabricating zero.
- Updated the same-day P&L badge to use the scoped resolver.

## Guardrails

- No live trading behavior changed.
- No engine restart was performed as part of this UI contract repair.
- Existing unrelated working-tree changes were not staged or modified.
