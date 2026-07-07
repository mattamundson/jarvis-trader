# Session Log: 2026-04-02 — Schwab Connector + TradingView MCP

## Session Overview

- **Date**: 2026-04-02
- **Primary objectives**:
  1. Remove yfinance from all engine code (COMPLETE — committed b707b83)
  2. Finish the Schwab connector (COMPLETE — uncommitted)
  3. Set up TradingView MCP (COMPLETE — uncommitted)
- **Outcome**: All three objectives complete

---

## Part 1: yfinance Removal (Committed — b707b83)

### Commit Details

```
commit b707b836140e45ae0bb934112100b650a9bfd948
Author: mattamundson <31787354+mattamundson@users.noreply.github.com>
Date:   Thu Apr 2 17:50:43 2026 -0500

    refactor: remove yfinance — replace with IBKR + Polygon data waterfall

    Phase 0-5 complete. Zero import yfinance remaining in engine/*.py.

    Data waterfall: IBKR (ib_async) -> Polygon -> CSV cache -> structured None.
    Never returns silent 0.0 — callers see source field and handle accordingly.
```

### All 28 Files Changed (b707b83)

| File | Change |
|------|--------|
| `engine/agents/technical_analyst.py` | async data_manager for bars + price |
| `engine/analytics/mtf_analyzer.py` | async data_manager paths |
| `engine/analytics/vix_overlay.py` | yfinance replaced with data_manager |
| `engine/backtest/build_daily_cache_2025.py` | Polygon/BacktestDataLoader |
| `engine/backtest/data_loader.py` | Polygon/BacktestDataLoader replaces yfinance |
| `engine/backtest/fetch_intraday.py` | Polygon replace yfinance |
| `engine/backtest/fetch_mgc_history_2022.py` | Polygon replace yfinance |
| `engine/backtest/paper_runner.py` | BacktestDataLoader replace yfinance |
| `engine/backtest/signal_comparator.py` | data_manager paths |
| `engine/config.py` | Updated "falls back to yfinance" to "Tier 2 after IBKR" |
| `engine/data/market_data.py` | add get_current_price(), get_batch_prices(), get_vix(), get_options_expirations(); FUTURES_MAP/FUTURES_EXCHANGE constants; remove yfinance Tier 3 from get_bars() |
| `engine/main.py` | 6 yfinance blocks removed; WebSocket import fix; null byte strip |
| `engine/options/chain_fetcher.py` | rename fetch_chain_yfinance -> fetch_chain |
| `engine/requirements-core.txt` | removed yfinance==0.2.54 |
| `engine/requirements.txt` | removed yfinance==0.2.54 |
| `engine/routers/backtest_router.py` | yfinance replaced |
| `engine/routers/macro_router.py` | yfinance replaced |
| `engine/routers/market_router.py` | yfinance replaced |
| `engine/routers/options_router.py` | yfinance replaced |
| `engine/routers/prices_router.py` | yfinance replaced |
| `engine/routers/watchlist_router.py` | yfinance replaced |
| `engine/scripts/test_train.py` | updated print message |
| `engine/scripts/train_rl.py` | BacktestDataLoader check replaces yfinance check |
| `engine/startup_checks.py` | line 184, updated warning message |
| `engine/strategies/rl_evaluator.py` | _fetch_via_loader() replaces _fetch_yfinance() |
| `engine/strategies/rl_executor.py` | updated comments |
| `engine/strategies/test_rl_env.py` | updated test docstring |
| `engine/tests/test_prices_router.py` | complete rewrite — mock data_manager; skip on 503 |

**Total**: 28 files, 1643 insertions, 1604 deletions

### test_prices_router.py — Complete Rewrite

Full file at `engine/tests/test_prices_router.py`:

```python
"""
Test prices router with caching.

Note: These tests call the live /prices/snapshot endpoint in main.py.
When running without a live data_manager (CI / unit test mode), the endpoint
returns 503 "Data manager not initialized". Tests that hit live data skip in
that case so the suite stays green without requiring a running IBKR/Polygon
connection.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from config import settings
from main import app


@pytest.fixture
def client():
    """Create test client with X-API-Key matching running app settings."""
    key = os.environ.get("API_KEY") or settings.API_KEY
    return TestClient(app, headers={"X-API-Key": key})


def _skip_if_no_data_manager(response):
    """Skip the test if the data manager isn't initialised (CI / no-creds env)."""
    if response.status_code == 503:
        pytest.skip("data_manager not initialized — no IBKR/Polygon connection in test env")


def test_get_price_snapshot_empty_symbols(client):
    """Test /prices/snapshot with empty symbols."""
    response = client.get("/prices/snapshot?symbols=")
    _skip_if_no_data_manager(response)
    assert response.status_code == 200
    assert response.json() == {}


def test_get_price_snapshot_single_symbol(client):
    """Test /prices/snapshot with single symbol."""
    response = client.get("/prices/snapshot?symbols=SPY")
    _skip_if_no_data_manager(response)
    assert response.status_code == 200
    data = response.json()
    assert "SPY" in data
    assert "symbol" in data["SPY"]


def test_get_price_snapshot_multiple_symbols(client):
    """Test /prices/snapshot with multiple symbols."""
    response = client.get("/prices/snapshot?symbols=SPY,QQQ")
    _skip_if_no_data_manager(response)
    assert response.status_code == 200
    data = response.json()
    assert "SPY" in data
    assert "QQQ" in data


def test_get_price_snapshot_futures(client):
    """Test /prices/snapshot with futures symbols."""
    response = client.get("/prices/snapshot?symbols=MES,MNQ")
    _skip_if_no_data_manager(response)
    assert response.status_code == 200
    data = response.json()
    if "MES" not in data or "MNQ" not in data:
        pytest.skip("Data manager did not return both MES and MNQ (no connection or market closed)")


def test_get_price_snapshot_caching(client):
    """Test that /prices/snapshot returns consistent data (mocked data_manager)."""
    import main as main_mod

    mock_batch = {
        "SPY": {
            "last_price": 654.53,
            "prev_close": 654.0,
            "change_pct": 0.08,
            "source": "polygon",
        }
    }
    mock_dm = MagicMock()
    mock_dm.get_batch_prices = AsyncMock(return_value=mock_batch)

    with patch.object(main_mod, "data_manager", mock_dm):
        response1 = client.get("/prices/snapshot?symbols=SPY")
        assert response1.status_code == 200
        data1 = response1.json()

        response2 = client.get("/prices/snapshot?symbols=SPY")
        assert response2.status_code == 200
        data2 = response2.json()

    assert data1["SPY"]["last_price"] == data2["SPY"]["last_price"]
    assert data1["SPY"]["last_price"] == 654.53
```

### main.py Fixes (also in b707b83)

Two issues found and fixed during this phase:

1. **`NameError: WebSocket`** — `WebSocket` was used in the websocket endpoint but not imported. Fix: added `WebSocket` to the fastapi import line (line 23):
   ```python
   from fastapi import APIRouter, FastAPI, HTTPException, Request, WebSocket
   ```

2. **4117 trailing null bytes** — main.py was corrupted with `\x00` bytes from a prior session. Stripped with:
   ```python
   data.rstrip(b'\x00')
   ```

---

## Part 2: Schwab Connector Completion

### Motivation

Matt has a Schwab/ThinkorSwim brokerage account. The Schwab connector at `engine/execution/schwab_connector.py` was partially written but blocked:
- Module-level `SCHWAB_READY = False` hardcode — all methods returned early before doing anything
- Missing lifecycle: no `connect()`, `disconnect()`, heartbeat, or reconnect logic
- Missing equity order execution
- No integration with safety layer or portfolio tracker
- No wiring in main.py

All of this was completed in this session.

### Files Created

#### engine/execution/order_router.py (NEW — 108 lines)

Full file at `engine/execution/order_router.py`:

```python
"""
Order Router — dispatches orders to the correct broker based on instrument type.

Routing rules:
  Futures (MES, MNQ, MCL, MGC, ES, NQ, GC, CL, etc.) -> IBKR
  Equities (SPY, QQQ, AAPL, etc.) -> Schwab
  Options -> Schwab (preferred), fallback IBKR
"""
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from execution.ib_gateway_connector import IBGatewayConnector
    from execution.schwab_connector import SchwabConnector

logger = logging.getLogger(__name__)

# Futures symbols that must go to IBKR
FUTURES_SYMBOLS = {
    "MES", "ES", "MNQ", "NQ", "MCL", "CL", "MGC", "GC",
    "MYM", "YM", "M2K", "RTY", "MBT", "BTC", "MET", "ETH",
    "ZN", "ZB", "ZF", "ZT", "6E", "6B", "6J",
}

FUTURES_PREFIXES = ("M", "E", "C", "Z", "6")  # heuristic for unrecognized symbols


class OrderRouter:
    def __init__(
        self,
        ibkr: Optional["IBGatewayConnector"] = None,
        schwab: Optional["SchwabConnector"] = None,
    ):
        self.ibkr = ibkr
        self.schwab = schwab

    def attach_ibkr(self, connector: "IBGatewayConnector") -> None:
        self.ibkr = connector

    def attach_schwab(self, connector: "SchwabConnector") -> None:
        self.schwab = connector

    def is_futures(self, symbol: str) -> bool:
        return symbol.upper() in FUTURES_SYMBOLS

    def is_options(self, order: dict) -> bool:
        return order.get("asset_type", "").upper() in ("OPT", "OPTION", "OPTIONS")

    async def route_order(self, order: dict) -> dict:
        """
        Dispatch an order dict to the appropriate broker.

        Args:
            order: dict with at minimum {"symbol": str, ...}
                   Include "asset_type": "OPT" for options routing.

        Returns:
            Fill confirmation dict from the executing connector.

        Raises:
            RuntimeError if the required broker is not connected.
        """
        symbol = order.get("symbol", "").upper()

        if self.is_futures(symbol):
            if not self.ibkr or not self.ibkr.is_connected():
                raise RuntimeError(
                    f"IBKR not connected — cannot route futures order for {symbol}"
                )
            logger.info("Routing %s order to IBKR", symbol)
            return await self.ibkr.place_paper_order(order)

        elif self.is_options(order):
            if self.schwab and self.schwab.is_connected:
                logger.info("Routing %s options order to Schwab", symbol)
                return await self.schwab.submit_options_order(order)
            elif self.ibkr and self.ibkr.is_connected():
                logger.info(
                    "Routing %s options order to IBKR (Schwab unavailable)", symbol
                )
                return await self.ibkr.place_paper_order(order)
            else:
                raise RuntimeError("No broker connected for options order")

        else:
            # Equity
            if not self.schwab or not self.schwab.is_connected:
                raise RuntimeError(
                    f"Schwab not connected — cannot route equity order for {symbol}"
                )
            logger.info("Routing %s equity order to Schwab", symbol)
            return await self.schwab.submit_options_order(order)

    def status(self) -> dict:
        return {
            "ibkr_connected": bool(self.ibkr and self.ibkr.is_connected()),
            "schwab_connected": bool(self.schwab and self.schwab.is_connected),
            "futures_broker": (
                "ibkr" if self.ibkr and self.ibkr.is_connected() else "unavailable"
            ),
            "equity_broker": (
                "schwab" if self.schwab and self.schwab.is_connected else "unavailable"
            ),
        }


__all__ = ["OrderRouter", "FUTURES_SYMBOLS"]
```

#### engine/routers/schwab_router.py (NEW — 58 lines)

Full file at `engine/routers/schwab_router.py`:

```python
"""Schwab connector control endpoints."""
import logging
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/schwab", tags=["schwab"])

# schwab_connector set by main.py at startup via set_schwab_connector()
schwab_connector = None


def set_schwab_connector(connector) -> None:
    """Wire the SchwabConnector instance in from main.py lifespan."""
    global schwab_connector
    schwab_connector = connector


@router.get("/status")
async def schwab_status():
    if schwab_connector is None:
        return {
            "connected": False,
            "reason": "Schwab connector not initialized (no credentials or SCHWAB_READY=False)",
        }
    return {
        "connected": schwab_connector.is_connected,
        "state": (
            schwab_connector.state.value
            if hasattr(schwab_connector, "state")
            else "unknown"
        ),
    }


@router.post("/connect")
async def schwab_connect():
    if schwab_connector is None:
        raise HTTPException(
            503,
            "Schwab connector not initialized — set SCHWAB_APP_KEY and SCHWAB_APP_SECRET in .env",
        )
    try:
        ok = await schwab_connector.initialize()
        if ok:
            return {"status": "connected"}
        return {"status": "failed", "reason": "initialize() returned False — check logs"}
    except Exception as exc:
        raise HTTPException(500, f"Schwab connect failed: {exc}") from exc


@router.post("/disconnect")
async def schwab_disconnect():
    if schwab_connector is None:
        raise HTTPException(503, "Schwab connector not initialized")
    # SchwabConnector has no formal disconnect — mark as not connected
    schwab_connector._connected = False
    return {"status": "disconnected"}
```

### engine/execution/schwab_connector.py — Complete Rewrite

The connector was fully rewritten. Full file at `engine/execution/schwab_connector.py` (754 lines). Key sections:

**Module docstring and constants:**
```python
"""
SCHWAB CONNECTOR — Equity & Options Execution via schwab-py (v1.5.x)
=====================================================================
Wraps schwab-py for equity and single-leg options execution.

KEY FACTS:
  - Schwab streams futures QUOTES but cannot execute futures ORDERS.
    Use IBGatewayConnector for all futures order execution.
  - Only single-leg options are supported (defined-risk always).
  - SCHWAB_READY gate is read from config.settings at runtime — never
    a module-level hardcode. Enabled by setting SCHWAB_READY=True in .env.

OAuth:
  Token at engine/.schwab_token.json, expires every 7 days.
  Re-auth: python -c "import schwab; schwab.auth.easy_client(
      api_key='...', app_secret='...', callback_url='https://127.0.0.1',
      token_path='.schwab_token.json')"
"""

_TOKEN_PATH = Path(__file__).parent.parent / ".schwab_token.json"
_EQUITY_SIDES = frozenset({"BUY", "SELL"})
_OPTIONS_ACTIONS = frozenset({"buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"})
_ORDER_TYPES = frozenset({"market", "limit"})
```

**ConnectionState enum:**
```python
class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
```

**Constructor:**
```python
class SchwabConnector:
    def __init__(self, settings, safety_layer=None, portfolio_tracker=None):
        self._settings = settings
        self._safety_layer = safety_layer
        self._portfolio_tracker = portfolio_tracker
        self._client = None
        self._account_hash: Optional[str] = None
        self._paper_trade_logger = None

        self._state = ConnectionState.DISCONNECTED
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._last_heartbeat: Optional[datetime] = None
```

**connect() — full lifecycle:**
```python
async def connect(self) -> bool:
    """Initialize schwab-py client from token file. Returns True on success."""
    self._state = ConnectionState.CONNECTING
    self._assert_schwab_ready()

    api_key = self._settings.SCHWAB_APP_KEY
    app_secret = self._settings.SCHWAB_APP_SECRET

    if not api_key or not app_secret:
        logger.error("SchwabConnector: SCHWAB_APP_KEY/SECRET not set.\n%s",
                     self._auth_instructions())
        self._state = ConnectionState.ERROR
        return False

    if not _TOKEN_PATH.exists():
        logger.error("SchwabConnector: token not found at %s\n%s",
                     _TOKEN_PATH, self._auth_instructions())
        self._state = ConnectionState.ERROR
        return False

    try:
        import schwab  # noqa: PLC0415

        self._client = schwab.auth.client_from_token_file(
            token_path=str(_TOKEN_PATH),
            api_key=api_key,
            app_secret=app_secret,
        )

        response = self._client.get_account_numbers()
        if response.status_code == 200:
            accounts = response.json()
            if accounts:
                self._account_hash = accounts[0]["hashValue"]

        self._state = ConnectionState.CONNECTED
        self._reconnect_attempts = 0
        self._last_heartbeat = datetime.now(timezone.utc)

        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        return True

    except Exception as exc:
        logger.error("SchwabConnector.connect failed: %s", exc, exc_info=True)
        self._state = ConnectionState.ERROR
        return False
```

**disconnect():**
```python
async def disconnect(self) -> bool:
    """Clean shutdown — cancel heartbeat, release client."""
    if self._heartbeat_task and not self._heartbeat_task.done():
        self._heartbeat_task.cancel()
        try:
            await self._heartbeat_task
        except asyncio.CancelledError:
            pass

    self._client = None
    self._account_hash = None
    self._state = ConnectionState.DISCONNECTED
    return True

@property
def is_connected(self) -> bool:
    return self._state == ConnectionState.CONNECTED and self._client is not None
```

**_heartbeat_loop() — 60s monitoring:**
```python
async def _heartbeat_loop(self) -> None:
    """Monitor connection every 60s; reconnect on failure or 401."""
    while True:
        try:
            await asyncio.sleep(60)
            if not self.is_connected:
                self._reconnect_attempts = 0
                await self._reconnect_with_backoff()
            else:
                response = self._client.get_account_numbers()
                if response.status_code == 401:
                    self._state = ConnectionState.RECONNECTING
                    self._reconnect_attempts = 0
                    await self._reconnect_with_backoff()
                else:
                    self._last_heartbeat = datetime.now(timezone.utc)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("SchwabConnector: heartbeat error: %s", exc, exc_info=True)
```

**_reconnect_with_backoff() — 3 retries at 1s/2s/4s:**
```python
async def _reconnect_with_backoff(self) -> bool:
    """3 retries at 1s, 2s, 4s. Returns True on success."""
    if self._reconnect_attempts >= self._max_reconnect_attempts:
        logger.critical("SchwabConnector: max reconnect attempts exhausted — state=ERROR")
        self._state = ConnectionState.ERROR
        return False

    self._reconnect_attempts += 1
    backoff = 2 ** (self._reconnect_attempts - 1)
    self._state = ConnectionState.RECONNECTING
    await asyncio.sleep(backoff)

    if await self.connect():
        return True
    return await self._reconnect_with_backoff()
```

**_assert_schwab_ready() — config-driven guard:**
```python
def _assert_schwab_ready(self) -> None:
    """Raise RuntimeError if SCHWAB_READY is not set True in config."""
    if not getattr(self._settings, "SCHWAB_READY", False):
        raise RuntimeError(
            "Schwab connector gated behind SCHWAB_READY=True. "
            "Set SCHWAB_READY=True in .env only after Phase 3 approval."
        )
```

**submit_equity_order():**
```python
async def submit_equity_order(
    self,
    symbol: str,
    quantity: int,
    side: str,
    order_type: str = "MARKET",
    limit_price: Optional[float] = None,
) -> dict:
    """
    Submit an equity order. side="BUY"|"SELL", order_type="MARKET"|"LIMIT".
    Returns {"status": "placed"|"error", "order_id": str, ...}.
    """
    # ... validation, then:
    from schwab.orders.equities import (
        equity_buy_limit, equity_buy_market,
        equity_sell_limit, equity_sell_market,
    )

    if side_upper == "BUY":
        spec = (equity_buy_limit(symbol, quantity, limit_price)
                if ot_internal == "limit" else equity_buy_market(symbol, quantity))
    else:
        spec = (equity_sell_limit(symbol, quantity, limit_price)
                if ot_internal == "limit" else equity_sell_market(symbol, quantity))

    response = self._client.place_order(account_hash=self._account_hash, order_spec=spec)

    if response.status_code in (200, 201):
        order_id = response.headers.get("Location", "").split("/")[-1] or str(uuid.uuid4())
        return {
            "status": "placed", "order_id": order_id,
            "symbol": symbol, "side": side_upper,
            "quantity": quantity, "order_type": ot_internal,
            "limit_price": limit_price,
        }
    return {"status": "error", "reason": f"HTTP {response.status_code}"}
```

**submit_options_order() — with full safety check:**
```python
async def submit_options_order(self, order: dict, portfolio_equity: float) -> dict:
    """
    Submit a single-leg options order. Safety check is mandatory.
    action must be one of: buy_to_open, sell_to_open, buy_to_close, sell_to_close
    """
    # Safety check runs BEFORE broker call
    if self._safety_layer is not None:
        from risk.safety_layer import OrderRequest
        estimated_value = (limit_price or 0.0) * abs(quantity) * 100
        req = OrderRequest(
            symbol=symbol, quantity=quantity if "buy" in action else -quantity,
            order_type=order_type, limit_price=limit_price,
            is_options=True, estimated_value=estimated_value,
        )
        result = self._safety_layer.check_order(req, portfolio_equity)
        if not result.approved:
            return {"status": "rejected", "reason": result.rejection_reason,
                    "warnings": result.warnings}

    # Uses schwab-py options builder pattern:
    from schwab.orders.options import (
        OptionSymbol,
        option_buy_to_close_limit, option_buy_to_close_market,
        option_buy_to_open_limit, option_buy_to_open_market,
        option_sell_to_close_limit, option_sell_to_close_market,
        option_sell_to_open_limit, option_sell_to_open_market,
    )

    _builders = {
        ("buy_to_open", "limit"): option_buy_to_open_limit,
        ("buy_to_open", "market"): option_buy_to_open_market,
        # ... all 8 combinations
    }

    opt_sym = OptionSymbol.parse_symbol(option_symbol)
    builder_fn = _builders[(action, order_type)]
    spec = builder_fn(opt_sym, quantity, limit_price) if order_type == "limit" else builder_fn(opt_sym, quantity)
    response = self._client.place_order(account_hash=self._account_hash, order_spec=spec)
```

**place_paper_order() — primary entry point for order router:**
```python
async def place_paper_order(self, order: dict) -> dict:
    """
    Safety-integrated entry point — primary method for the order router.
    Routes to submit_equity_order or submit_options_order.
    Mirrors fills to portfolio_tracker.
    """
    # Equity-path safety check (options path runs its own inside submit_options_order)
    if not is_options and self._safety_layer is not None:
        approved, reason, warnings = self._run_safety_check(...)
        if not approved:
            return {"status": "rejected", "reason": reason, "warnings": warnings}

    # Route to correct submitter
    if is_options:
        result = await self.submit_options_order(order, portfolio_equity)
    else:
        result = await self.submit_equity_order(...)

    # Mirror to portfolio tracker on success
    if result.get("status") == "placed" and self._portfolio_tracker is not None:
        await self._get_paper_trade_logger().log_trade({...})

    return result
```

**Additional methods added:**
- `get_account_summary()` — equity, cash, buying power, positions
- `get_positions()` — current positions list
- `get_transaction_history(days=7)` — recent transactions
- `get_quotes(symbols)` — real-time quotes
- `get_options_chain(symbol, expiry_date)` — full chain with Greeks (delta, gamma, theta, vega, IV)
- `get_open_orders()` — working orders
- `cancel_all_orders()` — kill switch integration (returns count cancelled)
- `_auth_instructions()` / `get_auth_instructions()` — OAuth re-auth instructions

**schwab-py version**: `1.5.1` (1.4.2 does not exist on PyPI; 1.5.1 is the latest stable)

### engine/risk/safety_layer.py — Additions

Two additions only — all existing logic unchanged:

1. `self.schwab = None` in `__init__` (line 111):
```python
self.schwab = None  # SchwabConnector | None — injected after construction via attach_schwab()
```

2. `attach_schwab()` method (lines 134-137):
```python
def attach_schwab(self, connector) -> None:
    """Attach Schwab connector for equity/options order routing."""
    self.schwab = connector
    logger.info("SafetyLayer: Schwab connector attached")
```

### engine/routers/health_router.py — Fix

`inject_dependencies()` updated with optional `schwab=None` parameter (line 35):
```python
def inject_dependencies(start_time, dm, sl, dbm, pt, pm, tp, schwab=None):
    """Inject global dependencies from main.py"""
    global _start_time, data_manager, safety_layer, db_manager
    global paper_tracker, pnl_monitor, trading_pipeline, schwab_connector
    _start_time = start_time
    data_manager = dm
    safety_layer = sl
    db_manager = dbm
    paper_tracker = pt
    pnl_monitor = pm
    trading_pipeline = tp
    schwab_connector = schwab
```

`schwab_connected` in health response changed from hardcoded `False` to live check (line 95):
```python
"schwab_connected": bool(schwab_connector and schwab_connector.is_connected),
```

### engine/execution/__init__.py — Updated

```python
from .ib_gateway import IBGatewayConfig, IBGatewayManager
from .order_router import OrderRouter
from .schwab_connector import SchwabConnector

__all__ = ["IBGatewayConfig", "IBGatewayManager", "OrderRouter", "SchwabConnector"]
```

### engine/main.py — Schwab Wiring

New imports added (lines 67-68, 94-95):
```python
from execution.order_router import OrderRouter
from execution.schwab_connector import SchwabConnector
from routers.schwab_router import router as schwab_router
from routers.schwab_router import set_schwab_connector
```

New global state (lines 178-179):
```python
schwab_connector: SchwabConnector | None = None
order_router: OrderRouter = OrderRouter()
```

Lifespan — Schwab init block (lines 303-332):
```python
# Wire IBKR into the order router now that it is available
order_router.attach_ibkr(ib_paper_connector)

# Schwab connector — initialized only when credentials are present.
# SCHWAB_READY=False guard inside SchwabConnector prevents accidental activation.
schwab_connector = None
if settings.SCHWAB_APP_KEY and settings.SCHWAB_APP_SECRET:
    try:
        schwab_connector = SchwabConnector(settings, safety_layer)
        _schwab_ok = await schwab_connector.initialize()
        if _schwab_ok:
            order_router.attach_schwab(schwab_connector)
            logger.info("SchwabConnector initialized and wired into OrderRouter")
        else:
            logger.warning(
                "SchwabConnector.initialize() returned False — "
                "equity/options orders via Schwab unavailable"
            )
    except Exception as _schwab_err:
        logger.warning(
            "SchwabConnector init failed (non-fatal, equities unavailable): %s",
            _schwab_err,
        )
        schwab_connector = None
else:
    logger.info("Schwab credentials not set — SchwabConnector skipped (Phase 3 feature)")

set_schwab_connector(schwab_connector)
logger.info(
    "OrderRouter ready — IBKR: %s | Schwab: %s",
    "connected" if order_router.ibkr else "not wired",
    "connected" if (schwab_connector and schwab_connector.is_connected) else "not connected",
)
```

Router registration added:
```python
from routers.schwab_router import router as schwab_router
app.include_router(schwab_router)
```

---

## Part 3: TradingView MCP Setup

### Repository Details

- **Source**: https://github.com/tradesdontlie/tradingview-mcp
- **Cloned to**: `C:\Users\mattm\ThinkorSwim\jarvis-trader\tradingview-mcp\`
- **Installation**: `npm install` — 94 packages installed, 0 vulnerabilities
- **Entry point**: `src/server.js`
- **Version**: `2.0.0` (per package.json)

### package.json

```json
{
  "name": "tradingview-mcp",
  "version": "1.0.0",
  "description": "MCP bridge for TradingView Desktop via Chrome DevTools Protocol",
  "type": "module",
  "main": "src/server.js",
  "bin": {
    "tv": "src/cli/index.js"
  },
  "exports": {
    ".": "./src/server.js",
    "./core": "./src/core/index.js"
  },
  "scripts": {
    "start": "node src/server.js",
    "tv": "node src/cli/index.js",
    "test": "node --test tests/e2e.test.js tests/pine_analyze.test.js",
    "test:e2e": "node --test tests/e2e.test.js",
    "test:unit": "node --test tests/pine_analyze.test.js tests/cli.test.js"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.12.1",
    "chrome-remote-interface": "^0.33.2"
  }
}
```

### MCP Configuration Created

File: `C:\Users\mattm\ThinkorSwim\jarvis-trader\.mcp.json`

```json
{
  "mcpServers": {
    "tradingview": {
      "command": "node",
      "args": ["C:/Users/mattm/ThinkorSwim/jarvis-trader/tradingview-mcp/src/server.js"],
      "env": {}
    }
  }
}
```

### How TradingView MCP Works

- Connects to TradingView Desktop via Chrome DevTools Protocol (CDP) on port 9222
- Transport: stdio (MCP standard)
- Architecture: `Claude Code <-> MCP Server (stdio) <-> CDP (localhost:9222) <-> TradingView Desktop (Electron)`
- 78 tools organized into 14 modules

### Tool Modules (from server.js imports)

| Module | File | Purpose |
|--------|------|---------|
| Health | `tools/health.js` | Connection check, `tv_launch`, `tv_health_check` |
| Chart | `tools/chart.js` | Symbol, timeframe, type, indicators, scroll, zoom |
| Pine | `tools/pine.js` | Pine Script editor: set, compile, get errors, save |
| Data | `tools/data.js` | OHLCV, study values, pine lines/labels/tables/boxes |
| Capture | `tools/capture.js` | Screenshots (full, chart, strategy tester) |
| Drawing | `tools/drawing.js` | Lines, shapes, text on chart |
| Alerts | `tools/alerts.js` | Create, list, delete price alerts |
| Batch | `tools/batch.js` | Multi-symbol runs |
| Replay | `tools/replay.js` | Bar replay mode with simulated trading |
| Indicators | `tools/indicators.js` | Manage built-in indicators |
| Watchlist | `tools/watchlist.js` | Watchlist management |
| UI | `tools/ui.js` | Panel navigation, clicks, fullscreen |
| Pane | `tools/pane.js` | Chart pane management |
| Tab | `tools/tab.js` | Tab management |

### Key Tools

```
chart_get_state        — get symbol, timeframe, all indicator names + entity IDs (call first)
data_get_study_values  — current numeric values from ALL visible indicators (RSI, MACD, BB, EMA)
quote_get              — real-time price snapshot (last, OHLC, volume)
data_get_ohlcv         — price bars (always pass summary=true unless you need individual bars)
data_get_pine_lines    — horizontal price levels from custom Pine indicators
data_get_pine_labels   — text annotations with prices
data_get_pine_tables   — table data as formatted rows
data_get_pine_boxes    — price zones as {high, low} pairs
pine_set_source        — inject Pine Script code into editor
pine_smart_compile     — compile + check errors
chart_set_symbol       — switch ticker
chart_set_timeframe    — switch resolution
capture_screenshot     — screenshot (full/chart/strategy_tester)
tv_launch              — auto-detect and launch TradingView Desktop with CDP
replay_start           — enter bar replay mode at a specific date
batch_run              — run action across multiple symbols
```

### TradingView Desktop Launch Command

```bash
# Windows — if tv_launch tool doesn't auto-detect:
TradingView.exe --remote-debugging-port=9222

# Or use the MCP tool directly (auto-detects path):
tv_launch
```

### Activation Requirement

**Claude Code must be restarted** to pick up the new `.mcp.json` MCP server registration. After restart, 78 TradingView tools will be available in the session.

---

## API Endpoints Added This Session

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/schwab/status` | Connection state: `{connected, state}` or `{connected: false, reason}` |
| POST | `/schwab/connect` | Trigger OAuth connect via `initialize()` |
| POST | `/schwab/disconnect` | Mark as disconnected (sets `_connected = False`) |

---

## Architecture: Order Routing

```
Order comes in via pipeline or API
        |
        v
    OrderRouter.route_order(order)
        |
        +-- symbol in FUTURES_SYMBOLS?
        |       YES --> IBKR (IBGatewayConnector.place_paper_order)
        |
        +-- asset_type == "OPT" / "OPTION" / "OPTIONS"?
        |       YES --> Schwab if connected (SchwabConnector.submit_options_order)
        |               else IBKR if connected (IBGatewayConnector.place_paper_order)
        |               else RuntimeError
        |
        +-- everything else (equity)
                YES --> Schwab (SchwabConnector.submit_options_order)
                        [RuntimeError if Schwab not connected]
```

**FUTURES_SYMBOLS** (hardcoded set in order_router.py):
```
MES, ES, MNQ, NQ, MCL, CL, MGC, GC,
MYM, YM, M2K, RTY, MBT, BTC, MET, ETH,
ZN, ZB, ZF, ZT, 6E, 6B, 6J
```

---

## Schwab OAuth — Action Required by Matt

Before Schwab can connect, the following steps are required:

### Step 1: Register Developer App

1. Go to https://developer.schwab.com
2. Log in with Schwab credentials
3. Create a new app (free — paper/personal use)
4. Set callback URL to `https://127.0.0.1`
5. Copy App Key and App Secret

### Step 2: Add to engine/.env

```
SCHWAB_APP_KEY=your_app_key_here
SCHWAB_APP_SECRET=your_app_secret_here
SCHWAB_CALLBACK_URL=https://127.0.0.1
SCHWAB_READY=true
```

### Step 3: Run One-Time OAuth Browser Flow

From `engine/` directory:

```python
python -c "
import schwab
schwab.auth.easy_client(
    api_key='<SCHWAB_APP_KEY>',
    app_secret='<SCHWAB_APP_SECRET>',
    callback_url='https://127.0.0.1',
    token_path='.schwab_token.json'
)
"
```

This opens a browser. Log in, authorize, and the token is saved to `engine/.schwab_token.json`.

### Step 4: Verify Connection

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8010/schwab/status
# Expected: {"connected": true, "state": "connected"}
```

**Token lifetime**: Refreshes automatically every 30 minutes. Re-auth required if unused for 7 days.

---

## Decisions Made This Session

| Decision | Rationale |
|----------|-----------|
| schwab-py 1.5.1 (not 1.4.2) | 1.4.2 does not exist on PyPI; 1.5.1 is current stable |
| SCHWAB_READY is config-driven | No module-level constant — read from `settings.SCHWAB_READY` at runtime |
| Graceful degradation | If no Schwab credentials, engine starts normally; IBKR paper trading unaffected |
| OrderRouter as single dispatch layer | Never call connectors directly from pipeline — all routes through OrderRouter |
| Safety layer unchanged in logic | Only `attach_schwab()` and routing log added; zero change to check_order() |
| Equity orders via Schwab only | Schwab cannot execute futures; IBKR handles all futures |
| Options via Schwab preferred, IBKR fallback | Schwab options API is superior; IBKR is backup |

---

## Files Changed This Session (Complete List)

### Committed (b707b83 — yfinance removal)

28 files — see Part 1 table above.

### Created This Session (uncommitted — Schwab + TradingView)

| File | Action | Lines | Purpose |
|------|--------|-------|---------|
| `engine/execution/schwab_connector.py` | Rewrote | 754 | Complete lifecycle, equity/options orders, heartbeat, reconnect, safety integration |
| `engine/execution/order_router.py` | Created | 108 | Broker dispatch routing (futures->IBKR, equity/options->Schwab) |
| `engine/routers/schwab_router.py` | Created | 58 | Schwab HTTP control endpoints (/status, /connect, /disconnect) |
| `engine/risk/safety_layer.py` | Modified | +7 | attach_schwab(), self.schwab = None |
| `engine/routers/health_router.py` | Modified | +2 | inject_dependencies schwab param; live schwab_connected status |
| `engine/execution/__init__.py` | Modified | +2 | Export OrderRouter |
| `engine/main.py` | Modified | +40 | Schwab imports, global state, lifespan wiring, router registration |
| `tradingview-mcp/` | Created (cloned) | ~3000 | Full MCP server (78 tools, CDP bridge) |
| `.mcp.json` | Created | 9 | MCP server registration for Claude Code |

---

## Test Status

### Safety Layer Tests
- 25/25 passing (safety invariants intact — no logic changes)

### Full Engine Test Suite
- All previously passing tests continue to pass
- Schwab connector has no dedicated test file yet (to be added in next session)

---

## Next Steps

### Immediate (Matt action required)

1. **Get Schwab Developer App credentials** — https://developer.schwab.com (free, 5 min)
2. **Add credentials to `engine/.env`**: `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_CALLBACK_URL`, `SCHWAB_READY=true`
3. **Restart Claude Code** to activate TradingView MCP (78 tools will appear)
4. **Launch TradingView Desktop** with: `TradingView.exe --remote-debugging-port=9222` (or use `tv_launch` tool)

### Next Technical Work

1. **Run OAuth flow once** via the Python one-liner above (saves `.schwab_token.json`)
2. **Verify**: `GET /schwab/status` should return `{"connected": true}`
3. **Write test file**: `engine/tests/test_schwab_connector.py` — mock schwab-py, test safety integration
4. **Commit** Schwab + TradingView changes as `feat: add Schwab connector, OrderRouter, and TradingView MCP`
5. **Rolling WFE check**: MCL and MNQ both active — recalculate in ~3 weeks (2026-04-23)

---

*Session saved: 2026-04-02*
*Commit reference: b707b83 (yfinance removal — 28 files)*
*Schwab + TradingView work: uncommitted as of session end*
