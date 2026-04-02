# Execution layer — IB connection boundary

## Single front door (production-shaped)

**`ib_gateway.py`** (`IBGatewayManager`) is the intended path for **real** Interactive Brokers work: `ib_async`, paper on port **4002**, **port 4001 (live) blocked**. Any new IB order/position code should live here or call into it.

## Paper simulation connector (not the live gateway)

**`ib_gateway_connector.py`** (`IBGatewayConnector`) is a **standalone async simulation** (slippage mock, `data/paper_trades.json`). It is **not** the same stack as `ib_gateway.py`. Imports must use the **`execution.*`** package (engine working directory), never `engine.execution.*`.

Optional **`portfolio_tracker`**: pass the same `PortfolioTracker` instance the FastAPI app uses so `PaperTradeLogger` can mirror full open/close round-trips onto mode **B** (see [PAPER_LEDGER_BOUNDARIES.md](../../docs/runbooks/PAPER_LEDGER_BOUNDARIES.md)).

## Other modules (thin or legacy)

| Module | Role |
|--------|------|
| `ibkr_executor.py` | Order execution helpers — should call into `ib_gateway` rather than open parallel connections. |
| `ib_connector.py` | Market data / connectivity helpers — prefer shared client state from gateway when refactoring. |
| `ib_data_feed.py` | Bars / historical data — keep separate from order routing but avoid a second IB socket where possible. |
| `paper_trade_logger.py` | JSON audit + optional mirror into `PortfolioTracker`. |

When adding features, extend **`ib_gateway.py`** or pass its client instance in — do not add a new `connect()` entry point without an explicit review (Tier 3 if it can reach live).
