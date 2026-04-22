# IB connector — behavior audit (P0.2)

**Purpose:** Trace how paper/IB state flows into the engine and health APIs. **Tier:** documentation only — no live-trading changes.

## Components

| Piece | Role |
|-------|------|
| [`engine/execution/ib_gateway_connector.py`](../../engine/execution/ib_gateway_connector.py) | `IBGatewayConnector`: when `PAPER_TRADING=True`, connects in **simulated** mode (local state + `PaperTradeLogger`); live IB via `ib_insync` is not implemented for order routing in this path. |
| [`engine/execution/ib_order_manager.py`](../../engine/execution/ib_order_manager.py) | Order orchestration layer used by execution paths; depends on config and safety. |
| [`engine/data/market_data.py`](../../engine/data/market_data.py) | `MarketDataManager` holds `ibkr` (connector instance); `health_check()` used by `/health/full`. |
| [`engine/routers/health_router.py`](../../engine/routers/health_router.py) | `/health` exposes `ibkr_connected` from `data_manager.ibkr.is_connected`; `/health/full` includes `ib_gateway` subsystem. |

## Failure modes (ops)

1. **Gateway down / wrong port** — `ibkr_connected` stays false; `/health/full` may show `ib_gateway` error or `not_configured` depending on initialization.
2. **`PAPER_TRADING=True` (default paper)** — Connector can report connected **without** a real TWS/Gateway socket; treat broker truth separately from “connector initialized”.
3. **Read-only or API-disabled account** — Orders fail at broker; safety layer still applies; positions must be reconciled via broker API when live path is enabled (future Tier 3).

## Related

- [P0_PAPER_IB_VERIFICATION.md](P0_PAPER_IB_VERIFICATION.md) — operator checklist.
- [PAPER_DATA_SOURCES.md](PAPER_DATA_SOURCES.md) — engine portfolio vs runner JSON.
