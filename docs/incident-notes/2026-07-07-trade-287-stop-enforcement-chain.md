# Incident — Trade #287 stop-enforcement chain (2026-07-07)

## Summary

Paper trade #287 (1 MGC, entry 4153.85, stop 4134.67) lost $1,236.50 and
tripped the daily kill switch. The loss itself was within the *stop's*
range, but the trade should never have been approved in the first place:
it was $191.83 over the $50/ticket pre-trade risk cap. Root-causing this
single bad fill surfaced four separate, real defects across the
order-execution and stop-persistence chain — one pre-trade (the risk gate
that should have blocked the trade), one operational (an LLM-call
crash-loop that degraded pipeline health around the same window), and two
post-trade (stop values that exist in memory but never reliably reach
storage or the broker). This note consolidates all four so the next
auditor doesn't re-trace the same paths from scratch, following the
pattern of [`2026-04-09-mcl-inverted-stop.md`](2026-04-09-mcl-inverted-stop.md).

## Chain of defects

| # | Defect | Fix | Status |
|---|---|---|---|
| 1 | Pre-trade risk gate defeated — two independent wiring bugs let a trade $191.83 over the $50/ticket cap through with zero risk computed | PR #324 | Merged |
| — | LLM-call concurrency/timeout issue degrading pipeline health in the same window | PR #325 | Merged |
| 2 | "Naked row" — OMS-bracket trades persist `paper_trades.stop_loss=NULL` even though the OMS holds the real stop in memory | PR #331 | Merged |
| 2b | Same naked-row class for IB-synced positions (no OMS bracket record exists for these at all) | PR #331 (follow-up commit) | Merged |
| 3 | Price-basis mismatch — bracket stop/target priced off a stale quote, never reconciled against the actual fill price | Not fixed — architecture decision needed | **Open, Amo-gated** |

## Defect 1 — pre-trade risk gate defeated (PR #324)

Two independent wiring bugs, either alone defeats the gate:

1. `engine/main.py:1075` — for a market order (no `limit_price`), the entry
   price fed to `execute_bracket()` fell back to the stop price instead of
   the real intended entry: `trade_dec.get("limit_price") or
   trade_dec.get("stop_price")`.
2. `engine/risk/safety_layer.py:1627` — `submit_paper_bracket_order()`'s
   `OrderRequest` never set `stop_price`, so `_check_trade_loss_gate()` hit
   its `if order.stop_price is None` early-return and auto-approved every
   bracket order regardless of size.

Both bugs were required simultaneously. Fix wires the real entry/stop
prices through correctly; a regression test
(`TestTrade287RegressionRiskGate` in `test_safety_layer.py`) replays
trade #287's exact numbers and asserts the post-fix gate now returns
`approved: False | TRADE_LOSS_LIMIT: Potential loss $191.83 exceeds max
$50.00 per ticket`.

**Live-trading path affected.** `OMSManager.execute_bracket()` is
identical code for paper and live — nothing branches on
`LIVE_TRADING_ENABLED` near either defect. Live orders are currently
blocked by that flag elsewhere in the stack, but this gate would be
defeated the same way if it's ever flipped without this fix.

## Defect 2 — naked row: OMS-bracket trades (PR #331)

`PortfolioTracker.open_trade()` has no `stop_loss` parameter, so OMS-v2
bracket-executed trades persist `paper_trades.stop_loss=NULL` even though
the OMS holds the real `stop_loss_price` in memory
(`execution/oms_v2.py::resolve_stop_for_symbol`, added alongside the
defect-1 fix). `main.py`'s `_monitor_open_stops()` already resolved that
in-memory value as a read-time fallback every 5 minutes, but never
persisted it back — the row stayed naked (`NULL`) indefinitely, invisible
to the dashboard and any other reader that trusts the column directly.

Fix adds `DatabaseManager.update_paper_trade_stop_loss()`, which
self-fetches `side`/`entry_price` for the row and re-applies the same
inverted-stop guard `insert_paper_trade` already uses (see
[`2026-04-09-mcl-inverted-stop.md`](2026-04-09-mcl-inverted-stop.md))
before writing — this is a second write path onto the same
safety-critical column and must not become a backdoor for persisting a
backwards stop. Wired into `_monitor_open_stops()`: when the OMS fallback
resolves a stop, it is now also persisted once (best-effort, non-fatal —
a persistence failure never blocks the stop-breach check the loop exists
to do).

## Defect 2b — naked row: IB-synced positions (PR #331 follow-up)

`IBOrderManager.sync_positions_from_ib()` is a *distinct* naked-row
source, found during the follow-up audit: it calls
`PortfolioTracker.open_trade()` for any IB position not yet known to the
tracker, with no stop_loss — and unlike defect 2, these positions were
never created through `execute_bracket()`, so they have no
`OMSManager.active_trades` entry at all. The read-time fallback in
`_monitor_open_stops()` cannot reach them either.

Fix queries `IBGatewayManager.get_open_orders()` for a resting STP/STP LMT
order matching the synced symbol and, if found, persists it via the same
guarded `update_paper_trade_stop_loss()` write path immediately after
`open_trade()`. Best-effort — a lookup or write failure never blocks the
position sync. If IB holds no stop for the position, `stop_loss` correctly
stays `NULL`: that is a genuinely naked broker position needing a
human-placed stop, not a bug in this code path.

## Defect 3 — price-basis mismatch (open, Amo-gated)

Flagged during the PR #331 audit but not fixed: the OMS bracket is priced
off a stale pre-trade quote (4134.67 in #287) vs. the actual fill
(4153.85). Traced through `oms_v2.execute_bracket()` →
`ib_order_manager.submit_bracket_order()` →
`safety_layer.submit_paper_bracket_order()`: the bracket's
`stop_loss`/`take_profit` are absolute prices computed by the caller from
a pre-trade quote, submitted to `place_bracket_order()`, and never
reconciled against the actual fill price — there is no fill-price return
value anywhere in that chain. The real fill price only becomes known
later, on a separate path (`PaperTradeLogger.log_trade()` →
`_maybe_mirror_to_tracker()`), which itself carries a `DeprecationWarning`
("retained for historical audit only") — not the right place to add new
logic either.

Closing this properly needs either (a) a fill-price callback that
re-bases the bracket's stop/target by the same point-distance once the
real fill is known, or (b) a decision to peg entries as LMT near the live
price instead of MKT. Both are architecture changes to the
order-execution path, not a surgical patch. **Needs Amo's call before any
code change.**

## Current state (verified 2026-07-09)

- PR #324 and #325 merged to master.
- PR #331 merged (naked-row backfill, both the OMS-bracket path and the
  IB-sync path).
- Defect 3 remains open, documented above, gated on an architecture
  decision.
- Live-audit of the running DB found 0 open `paper_trades` with
  `stop_loss=NULL` (kill switch has halted trading — no active positions
  to check against at audit time). The fix is verified-ready via unit
  tests but has not yet been exercised against a live naked row.

## If a future stop-enforcement gap is suspected

1. Check whether the position was opened via `execute_bracket()` (defect 2
   path — check `OMSManager.active_trades` for a matching entry) or via
   `sync_positions_from_ib()` (defect 2b path — check whether IB actually
   holds a resting stop order for the symbol).
2. Run `.venv\Scripts\python -m pytest engine/tests/test_stop_loss_invariants.py engine/tests/test_update_paper_trade_stop_loss.py engine/tests/test_sync_positions_stop_backfill.py -v`.
3. If the fill price and the bracket's stop/target don't reconcile against
   what was actually filled, that's defect 3 — still open, do not attempt
   a rushed patch; escalate for the architecture decision first.
