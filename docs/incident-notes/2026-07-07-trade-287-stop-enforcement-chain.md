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

**Note on defect 2/2b below:** the naked-row gap drew three independent fix
attempts (PRs #326, #331, #335, plus #356 which duplicated part of #335) that
overlapped on the same functions and files. Rather than merge them separately
and risk one silently undoing another (e.g. #335's function rename reverting
#326's tightened catastrophe-cap default), they were reconciled into a single
PR. What's described below is the reconciled result, not any one PR's
original diff verbatim.

## Chain of defects

| # | Defect | Fix | Status |
|---|---|---|---|
| 1 | Pre-trade risk gate defeated — two independent wiring bugs let a trade $191.83 over the $50/ticket cap through with zero risk computed | PR #324 | Merged |
| — | LLM-call concurrency/timeout issue degrading pipeline health in the same window | PR #325 | Merged |
| 2 | "Naked row" — `PortfolioTracker.open_trade()` had no `stop_loss` parameter at all, so every caller silently persisted `paper_trades.stop_loss=NULL` regardless of whether a real stop was known | Reconciled (#326 + #331 + #335, superseding #356) | Merged |
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

## Defect 2 — naked row: `open_trade()` never accepted a stop (reconciled)

`PortfolioTracker.open_trade()` had no `stop_loss` parameter at all, so
every call site — the human-approval flow, the OMS-bracket monitor's
read-time fallback, the IB-fill mirror, and the post-restart IB-position
reconcile — persisted `paper_trades.stop_loss=NULL` even when a real stop
was known somewhere in scope. Three independent fixes were drafted for
this (#326, #331, #335) plus one (#356) that duplicated part of #335; the
reconciled fix keeps the best of each rather than merging them separately:

- **Root fix (from #335):** `open_trade()` now accepts `stop_loss` and
  `stop_source` parameters, threaded through directly at the
  human-approval flow (`approval/service.py`) and the IB-fill mirror
  (`execution/paper_trade_logger.py`), synthesizing a defensive stop from
  the catastrophe-cap dollar-risk budget when no decision-time stop is in
  scope (`services.paper_stop_monitor.synthesize_fallback_stop`).
- **IB-position reconcile (combining #331 + #335):**
  `IBOrderManager.sync_positions_from_ib()` now prefers a **real** resting
  STP/STP LMT order from IB itself (`stop_source="ib_resting_order"`) —
  more accurate than a guess — and only falls back to the synthesized
  stop when IB holds none.
- **Periodic OMS-fallback backfill (from #331):**
  `DatabaseManager.update_paper_trade_stop_loss()` (new method, same
  inverted-stop guard as `insert_paper_trade`) lets
  `main.py::_monitor_open_stops()` persist the stop it resolves from
  `OMSManager.resolve_stop_for_symbol()` every cycle, instead of only
  holding it in memory each sweep.
- **Catastrophe-cap tightening (from #326):** the last-resort backstop
  (`max_loss_usd_from_env`, renamed public by #335) defaults to **$300**,
  not the original $750 — sized above the worst legitimate stop loss
  observed (~$133) but ~2.5x tighter against a #287-class disaster.
- **#356 closed as a duplicate** — its `resolve_stop_for_symbol()`
  most-recent-bracket fix was already fully contained in #335.

Best-effort throughout: a persistence failure on any of these paths never
blocks the stop-breach check or position sync it's attached to.

## Defect 3 — price-basis mismatch (open, Amo-gated)

Flagged during the naked-row audit but not fixed: the OMS bracket is priced
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
- Naked-row gap (#326/#331/#335/#356) reconciled into a single PR — see
  defect 2 above. Verified via the full touched-file test suite (98 tests
  passing).
- Defect 3 remains open, documented above, gated on an architecture
  decision.
- Live-audit of the running DB found 0 open `paper_trades` with
  `stop_loss=NULL` (kill switch has halted trading — no active positions
  to check against at audit time). The fix is verified-ready via unit
  tests but has not yet been exercised against a live naked row.

## If a future stop-enforcement gap is suspected

1. Check whether the position was opened via `execute_bracket()` (OMS-bracket
   path — check `OMSManager.active_trades` for a matching entry, and whether
   `main.py::_monitor_open_stops()`'s periodic backfill has run yet) or via
   `sync_positions_from_ib()` (check whether IB actually holds a resting stop
   order for the symbol, or whether the synthesized fallback applied).
2. Run `.venv\Scripts\python -m pytest engine/tests/test_stop_loss_invariants.py engine/tests/test_update_paper_trade_stop_loss.py engine/tests/test_sync_positions_stop_backfill.py engine/tests/test_stop_loss_threading.py engine/tests/test_paper_stop_monitor.py -v`.
3. If the fill price and the bracket's stop/target don't reconcile against
   what was actually filled, that's defect 3 — still open, do not attempt
   a rushed patch; escalate for the architecture decision first.
