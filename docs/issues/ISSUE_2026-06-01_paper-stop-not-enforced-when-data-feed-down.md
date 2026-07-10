# ISSUE — Paper stop-loss silently unenforced when the bar data feed is down

**Opened:** 2026-06-01
**Severity:** High (risk-management defect; paper-only today, but the same logic gates live)
**Status:** MITIGATED (stale reference swept 2026-07-09) — recommendation #2 (independent
in-process stop-monitor) is implemented and live: `engine/services/paper_stop_monitor.py`
(`PaperStopMonitor`, `PAPER_STOP_MONITOR_ENABLED`, default on). It decouples stop enforcement
from both the `paper_runner` cron and the historical-bar waterfall by pricing open positions
via `data_manager.get_current_price()` (the independent TICK path) every `interval_s` seconds.
Recommendations #1/#3/#4/#5 (data-starvation alerting, stale-bar fallback, tick-check on
`data_error`, real simulated broker-side stop) remain unimplemented — #2 alone already closes
the reported gap (silent, unprotected position during a bar-feed outage), so this is not a P0
regression risk, but the other four are still open hardening work if revisited.
**Trigger:** Trade #178 (MGC) lost **−$1,284 / −12.8% of the $10K paper account** because its stop never fired. Combined with #179 (−$70) it produced a **−16.1% day** that tripped the DAILY LOSS LIMIT kill-switch alert.

---

## What happened

| Field | Trade #178 (the loss) | Trade #179 (control) |
|---|---|---|
| symbol / side | MGC buy 1 | MGC buy 1 |
| entry | 4503.9 @ 2026-06-01T07:56Z | 4471.3 @ 2026-06-02T03:52Z |
| stop_loss | **4497.51** (−6.4 pts, ~$64 risk) | 4464.21 |
| exit | **4375.5 @ 20:45:00Z** (−128 pts, 122 pts past stop) | **4464.21** (== stop) @ 03:54Z |
| pnl | **−$1,284** | −$70 |
| stop_order_id / bracket_status | None / None | None / None |

Trade #178's stop was a sane, tight level. It was never honored — the position bled for ~13 hours and was force-flattened at a fixed session-close time. Trade #179 (same symbol, same setup) exited *exactly at its stop*, proving the stop logic itself is correct when it runs.

## Root cause (confirmed via code trace)

Paper stops are enforced by **one** mechanism only: the `paper_runner` bar-monitoring loop.
- `engine/backtest/paper_runner.py:454` `manage_open_position()` — checks `bar_low <= stop_loss` for longs and fires a simulated exit. Correct logic.
- It gets price via `_latest_mgmt_bar()` (`paper_runner.py:417`) → `fetch_bars()` → `GET /analyze/bars/{symbol}?interval=5m` → `data_manager.get_bars()` waterfall: **TradingView MCP → IBKR → SQLite cache (≤72h) → Polygon (futures-blocked) → CSV**.
- When **all** sources miss, `fetch_bars()` returns `None`, and `run_one_cycle()` (`paper_runner.py:767`) logs `{"action":"data_error"}` and **silently skips the cycle**. The open position is left unmanaged — no stop check, no alert.

On 2026-06-01 the IB Gateway (port 4002) was **down all day** (`ibkr_data_connected=False`), TV Desktop/CDP state was uncertain, and the SQLite bar cache went stale. So for the entire 07:56→20:45Z window every cycle hit `data_error` for MGC and the stop at 4497.51 was never evaluated. **Stop enforcement depends transitively on the bar feed, and the feed's failure mode is a silent no-op.** Hypothesis CONFIRMED.

There is **no** broker-side stop: `ALLOW_PAPER_SIMULATED_ORDERS=False` and the order path uses the mock `IBGatewayConnector` (`engine/execution/ib_gateway_connector.py`), so no working STP child is ever armed (consistent with `stop_order_id=None`). The bracket path (`engine/brokers/bracket_orders.py:245`) is inert in paper.

## The 20:45 force-exit

`engine/schedulers/eod_scheduler.py:628` `run_session_flatten()`, cron-registered at `eod_scheduler.py:791` for **20:45 UTC Mon–Fri**. It calls `PortfolioTracker.flatten_all_positions(market_price_fn=data_manager.get_current_price)` (`portfolio/tracker.py:1176`) — closes every open position at the *current market price regardless of stop*. That is what closed #178 at 4375.5, 122 pts below where the stop should have cut it.

## Why #179 differed

When #179 was opened (03:52Z on 6/2), a bar source was available, so a `paper_runner` cycle ~03:54Z saw `bar_low <= 4464.21` and fired the stop immediately (exit == stop is the `paper_runner.py:488` signature). The data-starvation that blinded #178 had cleared by then.

## The real lesson

The IB data-feed outage was **not cosmetic**. It silently disabled stop-loss enforcement, converting −$64 of planned risk into −$1,284 realized. Any time the price source feeding stop-enforcement is stale/down, open positions are unprotected and the system says nothing.

## Fix recommendations (ranked)

1. **Guard data-starved cycles (highest value, smallest change).** In `paper_runner.py:run_one_cycle()` (~line 767), track consecutive `data_error` counts per symbol-with-open-position; after N (~3, ≈15 min) send a WhatsApp/Discord alert and optionally force-flatten or halt new entries. Today this is a silent skip — make blindness loud.
2. **In-process synthetic stop-monitor (highest reliability).** New `engine/services/paper_stop_monitor.py` async loop (60s) in `main.py` lifespan: load open `paper_trades`, `get_tick_price()` per symbol (TV Tier 2.5 path, sub-200ms, independent of the historical-bar pipeline), close on breach. Decouples stop enforcement from the standalone paper_runner cron + bar waterfall.
3. **Stale-bar fallback for stop checks only.** In `_latest_mgmt_bar()` (`paper_runner.py:417`): if the only available bar is stale (>2h), still evaluate the stop (conservative) but block new entries.
4. **Tick-price stop check on the `data_error` branch.** When `df is None` for a symbol with an open position, attempt a single `get_current_price` check before skipping.
5. **(Long-term) Real simulated stop in the mock connector** when `ALLOW_PAPER_SIMULATED_ORDERS=True` — an internal order book that fires STP fills autonomously, independent of bar data.

A data-feed-health guard (#1) + an independent stop-monitor (#2) together close the gap: no silent holds, and stop enforcement no longer rides on the same feed that just proved it can vanish for 13 hours.

## Evidence files
- `engine/backtest/paper_runner.py` — `manage_open_position()` :454, `run_one_cycle()` :702, `_latest_mgmt_bar()` :417, silent `data_error` skip :767
- `engine/schedulers/eod_scheduler.py` — `run_session_flatten()` :628, cron :791 (20:45 UTC)
- `engine/portfolio/tracker.py` — `flatten_all_positions()` :1176
- `engine/data/market_data.py` — `get_bars()` :813, `get_current_price()` :959
- `engine/brokers/bracket_orders.py` — `submit_bracket()` :245 (inert in paper)
- `engine/execution/ib_gateway_connector.py` — mock connector (no real orders)
- DB: `engine/data/jarvis_trader.db` → `paper_trades` ids 178, 179
