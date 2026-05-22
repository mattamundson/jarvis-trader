# IB connector — behavior audit (P0.2)

**Purpose:** Trace how paper/IB state flows into the engine and health APIs. **Tier:** documentation only — no live-trading changes.

## Components

| Piece | Role |
|-------|------|
| [`engine/execution/ib_gateway_connector.py`](../../engine/execution/ib_gateway_connector.py) | `IBGatewayConnector`: when `PAPER_TRADING=True`, connects in **simulated** mode (local state + `PaperTradeLogger`); live IB via `ib_insync` is not implemented for order routing in this path. |
| [`engine/execution/ib_gateway.py`](../../engine/execution/ib_gateway.py) | `IBGatewayManager`: real ib_async client (port 4002 paper only). `place_paper_order` submits MKT/LMT/STP/STP_LMT orders with optional `parent_order_id` for child linking. |
| [`engine/brokers/bracket_orders.py`](../../engine/brokers/bracket_orders.py) | Bracket order builder/submitter: `build_bracket()` + `submit_bracket()` for atomic 3-leg IB brackets. Default ON via `ENABLE_BRACKET_ORDERS=1`. |
| [`engine/execution/ib_order_manager.py`](../../engine/execution/ib_order_manager.py) | Order orchestration layer used by execution paths; depends on config and safety. |
| [`engine/data/market_data.py`](../../engine/data/market_data.py) | `MarketDataManager` holds `ibkr` (connector instance); `health_check()` used by `/health/full`. |
| [`engine/routers/health_router.py`](../../engine/routers/health_router.py) | `/health` exposes `ibkr_connected` from `data_manager.ibkr.is_connected`; `/health/full` includes `ib_gateway` subsystem. |

## Bracket Orders (migration_031 / 2026-05-21)

Approved paper trades now submit as **atomic IB brackets** — three linked orders placed together so broker-side risk management survives engine crashes.

### How it works

```
Human approves → approval/service.py → execute_approved_trade()
                                         │
                     ENABLE_BROKER_BRACKETS=True
                   + ENABLE_BRACKET_ORDERS=1 (env)
                   + stop_price present in verdict
                                         │
                              SafetyLayer.submit_entry_with_stop()
                                         │
                         ┌───────────────┼───────────────┐
                      Entry MKT       STP child       LMT TP child
                    transmit=False   transmit=False   transmit=True
                    (root)           parentId=entry   parentId=entry
                                     ocaGroup=X       ocaGroup=X
```

The TP child's `transmit=True` triggers IB to process all three legs atomically. The shared `ocaGroup` means whichever child fills (STP or TP) automatically cancels the other.

### Where prices come from

Stop and target prices are **never computed independently** in this path — they come from the pipeline verdict:

| Price | Verdict fields consulted (priority order) |
|-------|------------------------------------------|
| `stop_price` | `stop_price`, `stop_loss` (from `trade_decision` or `decision` sub-dict) |
| `target_price` | `target_1`, `target_price`, `take_profit`, `target_2` |

If neither stop field is present, the bracket path is bypassed and a single market order is submitted (legacy behavior).

### Enabling / disabling

| Action | How |
|--------|-----|
| Default ON | `ENABLE_BRACKET_ORDERS=1` (absent = ON) |
| Disable globally | Set `ENABLE_BRACKET_ORDERS=0` in `engine/.env` — no restart needed, flag read fresh on every approval |
| Disable in config | Set `ENABLE_BROKER_BRACKETS=False` in `engine/.env` — requires config reload |

Both flags must be enabled for the bracket path to activate. Either flag alone can suppress it.

### Rollback on child failure

If the STP child placement fails:

1. `submit_bracket` (or `submit_entry_with_stop`) attempts to cancel the entry order.
2. Cancel success is logged at CRITICAL; cancel failure is also logged at CRITICAL.
3. The approval call returns `approved=False` so the paper_trades row is NOT opened.

If TP placement fails but STP succeeded, the bracket continues with entry + STP only (`bracket_status='partial'`). The entry is protected but there is no broker-side take-profit.

### DB columns (migration_031)

Three nullable columns added to `paper_trades`:

| Column | Content |
|--------|---------|
| `stop_order_id` | IB order ID of the STP child (TEXT, NULL for single-order path) |
| `target_order_id` | IB order ID of the TP child (TEXT, NULL if TP failed or not requested) |
| `bracket_status` | `'attached'` / `'partial'` / `'failed'` / `'detached_manually'` / NULL |

### Manual child detach procedure

If you want to flatten a position's stop or target via TWS without closing the parent:

1. Open TWS → Order Management → open orders for the account.
2. Right-click the STP or LMT child order → **Cancel Order**.
3. This leaves the parent fill intact; the position is now unprotected.
4. To record the detach in the DB, run:
   ```sql
   UPDATE paper_trades
      SET bracket_status = 'detached_manually'
    WHERE trade_id = '<trade_id>';
   ```
5. Update the stop in the JARVIS portfolio tracker if you replace with a manual stop.

Do NOT cancel the parent entry if children are still live — IB will propagate the cancel to all linked children automatically.

## Failure modes (ops)

1. **Gateway down / wrong port** — `ibkr_connected` stays false; `/health/full` may show `ib_gateway` error or `not_configured` depending on initialization.
2. **`PAPER_TRADING=True` (default paper)** — Connector can report connected **without** a real TWS/Gateway socket; treat broker truth separately from "connector initialized".
3. **Read-only or API-disabled account** — Orders fail at broker; safety layer still applies; positions must be reconciled via broker API when live path is enabled (future Tier 3).
4. **Bracket STP fails on instant MKT fill** — IB paper account sometimes fills market orders before the STP child is registered. The rollback cancel path fires. If the cancel also fails, the position is live without a broker-side stop (engine-side safety layer still monitors). Set `ENABLE_BRACKET_ORDERS=0` as a workaround until the race is resolved in a future IB API version.

## Entry Price Sanity Check (2026-05-21)

Before an approved trade reaches IB submission, `approval/service.py:approve_pending_trade()`
runs an entry price sanity check that rejects the order if:

```
|entry_price - market_price| / ATR > ENTRY_PRICE_SANITY_MAX_ATR_DELTA   (default 1.0)
```

**Motivation:** 2026-05-09 phantom-trade incident — a `stop_loss` field value (7398.5481)
was copied into `entry_price` for 6 MES SHORT orders. Real market was ~7385;
delta/ATR ≈ 1.35. No IB order fired (paper mode), but the corrupted entries were
logged as legitimate positions. This check blocks such corrupted prices at the
order surface.

**HTTP response on failure:** `422 Unprocessable Entity` with a human-readable reason.
The approval row status remains `pending` — no paper_trade row is created.

**Module:** `engine/risk/entry_price_sanity.py` (additive — does NOT modify `safety_layer.py`).

**Env vars:**

| Variable | Default | Meaning |
|---|---|---|
| `ENABLE_ENTRY_PRICE_SANITY` | `1` | Opt-out: set `0` to disable |
| `ENTRY_PRICE_SANITY_MAX_ATR_DELTA` | `1.0` | ATR-multiple threshold |

**Check also runs at enqueue** in `scheduler/pipeline_autonomous.py` so corrupted
verdicts are rejected before they enter the approval queue.

**Edge case — low-volatility / overnight regimes:** When ATR is very small, a genuine
rounding slip may exceed 1.0 ATR. Consider raising `ENTRY_PRICE_SANITY_MAX_ATR_DELTA`
to 2.0 for overnight sessions, or add an absolute ATR floor in a future iteration.

## Related

- [P0_PAPER_IB_VERIFICATION.md](P0_PAPER_IB_VERIFICATION.md) — operator checklist.
- [PAPER_DATA_SOURCES.md](PAPER_DATA_SOURCES.md) — engine portfolio vs runner JSON.
- [PAPER_TRADING_APPROVAL.md](PAPER_TRADING_APPROVAL.md) — full approval flow.
- [AUTONOMOUS_PIPELINE_RUNBOOK.md](AUTONOMOUS_PIPELINE_RUNBOOK.md) — autonomous scheduler gates.
