# Execution layer — IB connection boundary

## Single front door

**`ib_gateway.py`** is the intended **sole** Interactive Brokers connection for orders, positions, and account paths that touch the live API. It owns the **port 4001 (live) safety block** — any new IB code must not bypass this module.

## Other modules (thin or legacy)

| Module | Role |
|--------|------|
| `ibkr_executor.py` | Order execution helpers — should call into `ib_gateway` rather than open parallel connections. |
| `ib_connector.py` | Market data / connectivity helpers — prefer shared client state from gateway when refactoring. |
| `ib_data_feed.py` | Bars / historical data — keep separate from order routing but avoid a second IB socket where possible. |

When adding features, extend **`ib_gateway.py`** or pass its client instance in — do not add a new `connect()` entry point without an explicit review (Tier 3 if it can reach live).
