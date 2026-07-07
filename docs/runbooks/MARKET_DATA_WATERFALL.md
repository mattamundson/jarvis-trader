# Market data waterfall (audit reference)

**Code:** [engine/data/market_data.py](../../engine/data/market_data.py) — `MarketDataManager`.

## OHLCV bars (`get_bars`)

| Tier | Condition | Source |
|------|-----------|--------|
| 1 | `ibkr` exists and `ibkr.is_connected` | IBKR historical bars |
| 2 | `polygon` configured | Polygon aggs (micro symbols mapped via `POLYGON_FUTURES_MAP`) |
| 3 | CSV cache file present | `_load_csv_cache` — **rejected if last bar &gt; 2 days old** (staleness guard) |

## Current price (`get_current_price`)

| Tier | Condition | Notes |
|------|-----------|--------|
| 1 | IB connected | `get_snapshot_price` — if `last_price` truthy, return |
| 2 | Schwab connected | Real-time quote |
| 2.5 | TradingView feed available | Optional CDP bridge |
| 3 | Polygon | Mapped symbol for micros |
| 4 | CSV | Last daily close — **no 2-day staleness check** (unlike `get_bars`); treat as last-resort |

## Operations guidance

- For **paper validation** with fresh futures prices, prefer **IB Gateway on `IBKR_PORT` (4002 paper)** so Tier 1 succeeds; see [P0_PAPER_IB_VERIFICATION.md](P0_PAPER_IB_VERIFICATION.md) and [IB_RECONNECT_AND_HEALTH.md](IB_RECONNECT_AND_HEALTH.md).
- **CSV** is appropriate for **offline backtest / fixture** work, not as a substitute for live IBKR+Polygon when validating intraday signals.

## Tests

Regression: [engine/tests/test_market_data_waterfall.py](../../engine/tests/test_market_data_waterfall.py).
