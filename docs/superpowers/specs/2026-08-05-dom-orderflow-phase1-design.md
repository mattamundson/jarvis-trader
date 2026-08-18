# DOM / Order-Flow Service — Phase 1 Design

**Date:** 2026-08-05
**Status:** Draft — pending Amo review
**Author:** Claude (brainstormed with Amo)

## Context

jarvis-trader has never ingested Level 2 / DOM (depth of market) or order-flow-imbalance
data, despite IB Gateway already being connected (paper, port 4002) and offering
`reqMktDepth` for free. This gap surfaced 2026-08-04 alongside two related, explicitly
out-of-scope gaps: dark pool prints (deferred in `docs/ROADMAP_2026-Q2-Q4.md:512` — no
reliable free futures data source exists) and real unusual-options-flow data (open TODO
in `docs/analysis/WIDGETS_AND_DECISIONS.md:1437`, separate from the existing GEX/dealer-
positioning calculation in `engine/analytics/options_flow.py`). This spec covers DOM/
order-flow only; unusual-options-flow is a separate future spec.

**Hard constraint:** IBKR does not sell historical L2 depth, and nothing in this repo has
ever stored it. Any order-flow-imbalance signal built on this data **cannot go through
the existing gate-v2 backtest pipeline** (walk-forward/DSR require historical data this
data source cannot provide). Validation must be live/forward-only.

## Goal

Phase 1: ship a cheap, safe, purely-informational DOM/order-flow visualization for MES,
isolated from anything safety-critical, so Amo can build real intuition about whether
this signal is worth anything before any commitment to Phase 2 (feeding it into the
trading pipeline).

Phase 2 (not built in this spec, architected for): once Phase 1 has run long enough to
judge, optionally wire the computed imbalance metric into the pipeline as a new
forward-graded signal, with its own validation harness (since gate-v2 doesn't apply).

## Scope

- **Instrument:** MES only (the only actively-trading approved instrument; other
  instruments are halted per `engine/CLAUDE.md` Active Instruments table).
- **Persistence:** on, from day one — computed snapshots stored every 10s, so the
  forward-history dataset Phase 2 would need starts accumulating now rather than
  whenever Phase 2 begins.
- **Explicitly out of scope for Phase 1:** any wiring into `engine/agents/pipeline.py`,
  any `[safety-review]`-tagged code path, a Phase-2 forward-grading harness, alerting,
  any instrument beyond MES.

## Architecture

A new isolated FastAPI service, `engine/domflow/`, port **8030** (next free port after
`jarvis-bridge-api`'s 8020), run as its own pm2 app — the same isolation pattern
`jarvis-bridge-api` already uses to keep non-critical data out of the main engine
process. It holds its own `ib_insync` connection to IB Gateway using a distinct client
ID so it cannot collide with the main engine's connection. It imports nothing from
`engine/risk/`, `engine/config.py`, or any safety-critical module — this is a read-only
market-data consumer with no path to placing an order.

Rejected alternatives:
- Wiring `reqMktDepth` directly into the main engine process: adds streaming-data load
  and a new IBKR subscription directly onto the safety-critical process for a Phase-1
  feature that has zero trading impact. Cuts against this repo's "surgical changes only"
  discipline (`meta-discipline.md`).
- A paid order-flow data vendor instead of free IBKR depth: better historical backfill,
  but IB Gateway is already connected and free, and the signal hasn't been validated to
  have any edge yet. Premature spend.

## Components

- `engine/domflow/main.py` — FastAPI app, CORS/structure mirrors `engine/api/main.py`
- `engine/domflow/ib_client.py` — wraps `reqMktDepth` for MES, maintains an in-memory
  order book (top 10 levels bid/ask), recomputes on each update
- `engine/domflow/imbalance.py` — pure function, no I/O: given a book snapshot, compute
  `imbalance_ratio = bid_volume / (bid_volume + ask_volume)` at top-N levels (N=5,
  configurable). This is the actual signal; everything else is plumbing.
- `engine/domflow/storage.py` — writes a snapshot row every 10s (not every tick — raw L2
  updates arrive multiple times/sec, which is noise for a forward-grading use case, not a
  scalping signal)

## Data flow

IB Gateway → `ib_client.py` (live book) → `imbalance.py` (computed metric) → SQLite
(`engine/domflow/domflow.db`, a new file, deliberately not `jarvis_trader.db` — keeps
this feature cleanly separable/droppable if it turns out not to be worth keeping) →
FastAPI endpoints `GET /domflow/mes/latest` and `GET /domflow/mes/history?minutes=N` →
dashboard.

## Storage schema

```sql
CREATE TABLE domflow_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    best_bid REAL, best_ask REAL, mid_price REAL, spread REAL,
    bid_volume_top5 INTEGER, ask_volume_top5 INTEGER,
    imbalance_ratio REAL,          -- bid_vol / (bid_vol + ask_vol), the actual signal
    raw_book_json TEXT             -- full top-10 levels, for Phase 2 flexibility
                                    -- without a schema migration
);
CREATE INDEX idx_domflow_symbol_ts ON domflow_snapshots(symbol, ts_utc);
```

## Dashboard

New `fetchDomflow`/`postDomflow` pair in `dashboard/lib/api.ts`, mirroring the existing
`fetchEngine`/`postEngine` shape (points at a `DOMFLOW_BASE` env-configurable URL, port
8030). This deliberately does **not** copy `jarvis-bridge-api`'s dashboard consumption
pattern — that integration is a legacy static HTML page
(`public/strategy-c-command-center.html`) that bypasses the typed `fetchEngine`
convention this repo's `coding-style.md` actually mandates. New page
`dashboard/app/domflow/page.tsx`:
- Live imbalance ratio as a gauge/sparkline, SWR polling every 5-10s
- Badge using the existing strict variants (`bull` when imbalance >0.6, `bear` when
  <0.4, `neutral` between; `live`/`static` per the Trust-Pane data-provenance
  convention)
- Short history chart from `/domflow/mes/history`

## Error handling

`ib_client.py` follows this repo's async-with-graceful-fallback convention: if
`reqMktDepth` disconnects or IB Gateway is unreachable, the service keeps running and
the endpoint returns the last-known snapshot with an explicit `stale: true` +
`age_seconds` field — it never silently serves stale data as fresh (per this repo's
numeric-accuracy verification rule). No exceptions swallowed silently; all errors
surface via `HTTPException` per this repo's FastAPI convention.

## Testing

`engine/domflow/tests/test_imbalance.py` — pure unit tests on `imbalance.py` with known
book inputs → expected ratio (all-bid book → 1.0, empty book → handled without
div-by-zero, since the pure function has no I/O it needs no IBKR mock).

**Verification level this spec can promise up front: type-checks + unit-tested only.**
Per this repo's verification discipline, "works"/"done" will not be claimed until the
service has actually been run against the real IB Gateway paper connection and a real
stored row has been observed end-to-end (live depth → computed imbalance → SQLite row →
dashboard render) — not before.

## Open questions for Phase 2 (not answered here, flagged for later)

- What forward-grading window/threshold determines "this signal is worth feeding into
  the pipeline"? (Amo's earlier answer was "not sure yet, lay out the trade-offs" —
  deferred to a Phase 2 spec once Phase 1 has real observed data to reason about.)
- Where does a forward-only signal's grading result live, given gate-v2's
  `pf_ci_lower`/`p_edge`/`mc_95th_dd`/`dsr` framework assumes historical backtest data?
