"""
JARVIS TRADER — IB API Connection Module
========================================
Paper trading only. Supports both IB Gateway (port 4002) and TWS (port 7497).
Live trading ports — Gateway 4001 and TWS 7496 — are permanently disabled.

Library: ib_async (successor to ib_insync — same API, actively maintained).
         Imported as `ib_insync` alias for backward compatibility.

Usage:
    # IB Gateway paper (default)
    config = IBGatewayConfig(account="DU1234567")
    gw = IBGatewayManager(config)
    await gw.connect()

    # TWS paper
    config = IBGatewayConfig(port=7497, account="DU1234567")
    gw = IBGatewayManager(config)
    await gw.connect()

    order_id = await gw.place_paper_order("MES", "BUY", 1)
    await gw.disconnect()
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Optional


def _nearest_front_month(reference: Optional[date] = None) -> str:
    """
    Return the nearest active front-month expiry as "YYYYMM" (IB contract month format).

    Used for monthly-expiry futures (MCL crude oil) where the front month rolls
    approximately on the 25th of the month prior to delivery.
    """
    ref = reference or date.today()
    # If we're past the 20th, the current month has likely rolled — use next month
    if ref.day >= 20:
        if ref.month == 12:
            return f"{ref.year + 1}01"
        return f"{ref.year}{ref.month + 1:02d}"
    return f"{ref.year}{ref.month:02d}"


def _nearest_quarterly_expiry(reference: Optional[date] = None) -> str:
    """
    Return the nearest active quarterly expiry as "YYYYMM".

    IB accepts the contract month in YYYYMM format and resolves the exact
    expiry date itself. Using YYYYMMDD caused "No security definition" errors
    because IB treats that as an exact date rather than a contract month.

    Quarterly months: March (3), June (6), September (9), December (12).
    """
    ref = reference or date.today()
    quarterly_months = [3, 6, 9, 12]
    expiry_day_approx = 21
    for month in quarterly_months:
        candidate = date(ref.year, month, expiry_day_approx)
        if candidate > ref:
            return f"{ref.year}{month:02d}"
    # All quarterly months in current year passed — use March of next year
    return f"{ref.year + 1}03"


logger = logging.getLogger(__name__)

# ── Library availability ──────────────────────────────────────────────────────
# ib_async is the successor to ib_insync (same API, drop-in replacement).
# requirements.txt pins ib_async==0.9.86.

IB_INSYNC_AVAILABLE = False
IB = None
Contract = None
Stock = None
Future = None
MarketOrder = None
LimitOrder = None
StopOrder = None
StopLimitOrder = None

try:
    # ib_async ships the same public namespace as ib_insync
    from ib_async import (  # type: ignore[import]
        IB,
        Contract,
        Future,
        LimitOrder,
        MarketOrder,
        Option,
        Stock,
        StopLimitOrder,
        StopOrder,
    )
    from ib_async import (
        util as ib_util,
    )

    IB_INSYNC_AVAILABLE = True
    logger.info("ib_async loaded successfully (IB_INSYNC_AVAILABLE=True)")
except ImportError:
    try:
        # Fallback: some installs still use the original package name
        from ib_insync import (  # type: ignore[import]  # noqa: F401
            IB,
            Contract,
            Future,
            LimitOrder,
            MarketOrder,
            Stock,
            StopLimitOrder,
            StopOrder,
        )
        from ib_insync import (  # noqa: F401
            util as ib_util,
        )

        IB_INSYNC_AVAILABLE = True
        logger.info("ib_insync loaded successfully (IB_INSYNC_AVAILABLE=True)")
    except ImportError:
        logger.warning(
            "Neither ib_async nor ib_insync is installed. "
            "IBGatewayManager will start but all broker calls will fail. "
            "Install with: pip install ib_async>=0.9.86"
        )


# ── Futures symbol map ────────────────────────────────────────────────────────
# Micro-futures traded by JARVIS.  Key = front-month symbol root JARVIS uses.
# Values: (ib_local_symbol_root, exchange, currency, multiplier)

FUTURES_SYMBOL_MAP: dict[str, dict] = {
    # MES — Micro E-mini S&P 500. IB requires exchange="CME" (not GLOBEX) for
    # contract qualification. Symbol is "MES" (not the standard "ES" underlying).
    "MES": {
        "underlying": "MES",
        "exchange": "CME",
        "currency": "USD",
        "secType": "FUT",
        "multiplier": "5",
    },
    # MNQ — Micro E-mini Nasdaq-100. exchange="CME" required for qualification.
    "MNQ": {
        "underlying": "MNQ",
        "exchange": "CME",
        "currency": "USD",
        "secType": "FUT",
        "multiplier": "2",
    },
    # Micro Crude Oil — NYMEX (approved paper-trading instrument, WFE=0.82)
    # Error 321 root cause: MCL was missing from this map and fell back to Stock().
    # Fix: explicitly map MCL to NYMEX with correct contract metadata.
    "MCL": {
        "underlying": "MCL",
        "exchange": "NYMEX",
        "currency": "USD",
        "secType": "FUT",
        "multiplier": "100",
    },
    # Micro Gold — COMEX
    "MGC": {
        "underlying": "MGC",
        "exchange": "COMEX",
        "currency": "USD",
        "secType": "FUT",
        "multiplier": "10",
    },
    # Extended micro-futures for future use
    "MYM": {
        "underlying": "YM",
        "exchange": "ECBOT",
        "currency": "USD",
        "secType": "FUT",
        "multiplier": "0.5",
    },
    "M2K": {
        "underlying": "RTY",
        "exchange": "GLOBEX",
        "currency": "USD",
        "secType": "FUT",
        "multiplier": "5",
    },
}

# ── Config ────────────────────────────────────────────────────────────────────

# SAFETY: Live trading ports are permanently disabled in this module.
# Gateway live = 4001, TWS live = 7496. Both are rejected at construction.
LIVE_TRADING_PORTS = frozenset({4001, 7496})
PAPER_TRADING_PORTS = frozenset({4002, 7497})  # Gateway paper, TWS paper

# Backward-compat singletons — point at the original Gateway-only values for
# any external caller importing them. Internal logic uses the *_PORTS sets.
LIVE_TRADING_PORT = 4001
PAPER_TRADING_PORT = 4002


def _broker_label(port: int) -> str:
    """Return 'Gateway' or 'TWS' for log messages based on configured port."""
    if port in (4001, 4002):
        return "Gateway"
    if port in (7496, 7497):
        return "TWS"
    return "IB"


@dataclass
class IBGatewayConfig:
    """
    Configuration for an IB API paper-trading connection.

    Default port is 4002 (Gateway paper). Set port=7497 to target TWS paper.
    Live ports — 4001 (Gateway) and 7496 (TWS) — raise ValueError at construction.
    """

    host: str = "127.0.0.1"
    port: int = PAPER_TRADING_PORT  # 4002 (Gateway paper) by default; 7497 = TWS paper
    client_id: int = 1
    timeout: float = 10.0
    readonly: bool = False
    account: str = ""  # IB paper account ID, e.g. "DU1234567"

    def __post_init__(self) -> None:
        # SAFETY: Live trading ports (Gateway 4001, TWS 7496) are permanently disabled.
        if self.port in LIVE_TRADING_PORTS:
            raise ValueError(
                f"SAFETY VIOLATION: Port {self.port} (live trading) is permanently "
                "disabled in IBGatewayManager. Paper trading only — use 4002 (Gateway) "
                "or 7497 (TWS)."
            )
        if self.port not in PAPER_TRADING_PORTS:
            logger.warning(
                "Non-standard IB API port %d. Expected one of %s (paper).",
                self.port,
                sorted(PAPER_TRADING_PORTS),
            )


# ── Status enum ──────────────────────────────────────────────────────────────


class IBConnectionStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# ── Manager ───────────────────────────────────────────────────────────────────


class IBGatewayManager:
    """
    Manages an ib_async / ib_insync connection to IB Gateway for paper trading.

    SAFETY CONTRACT
    ---------------
    - Port 4001 (live trading) is REJECTED at construction time and at connect().
    - The module will never route orders to a live account.
    - All methods are safe to call even when IB_INSYNC_AVAILABLE=False; they
      return sensible error results rather than raising.

    Thread / event-loop model
    -------------------------
    ib_async uses its own event loop wrapper. All public coroutines in this class
    are async-friendly and can be awaited from a FastAPI/uvicorn async context.
    """

    def __init__(self, config: Optional[IBGatewayConfig] = None) -> None:
        if config is None:
            config = IBGatewayConfig()

        # SAFETY: Live trading ports (Gateway 4001, TWS 7496) are permanently disabled.
        if config.port in LIVE_TRADING_PORTS:
            raise ValueError(
                f"SAFETY VIOLATION: Port {config.port} (live trading) is permanently "
                "disabled in IBGatewayManager. Paper trading only — use 4002 (Gateway) "
                "or 7497 (TWS)."
            )

        self._config = config
        self._ib: Optional[object] = None  # IB() instance when available
        self._status = IBConnectionStatus.DISCONNECTED
        self._connect_time: Optional[float] = None
        self._last_error: Optional[str] = None

        logger.info(
            "IBGatewayManager created | broker=%s host=%s port=%d client_id=%d account=%s",
            _broker_label(config.port),
            config.host,
            config.port,
            config.client_id,
            config.account or "(auto-detect)",
        )

    # ── Connection ────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Connect to the configured IB API endpoint (Gateway paper 4002 or TWS paper 7497).

        Returns True on success, False on failure.
        Sets self._status to CONNECTED or ERROR accordingly.
        """
        # SAFETY: Live trading ports (Gateway 4001, TWS 7496) are permanently disabled.
        if self._config.port in LIVE_TRADING_PORTS:
            logger.critical(
                "SAFETY VIOLATION in connect(): port %d (live trading) rejected. Aborting.",
                self._config.port,
            )
            self._status = IBConnectionStatus.ERROR
            self._last_error = f"Port {self._config.port} (live trading) is permanently disabled"
            return False

        if not IB_INSYNC_AVAILABLE:
            logger.error(
                "connect() called but ib_async/ib_insync is not installed. "
                "Run: pip install ib_async>=0.9.86"
            )
            self._status = IBConnectionStatus.ERROR
            self._last_error = "ib_async not installed"
            return False

        if self._status == IBConnectionStatus.CONNECTED and self._ib is not None:
            if self._ib.isConnected():
                logger.debug("Already connected to IB Gateway — skipping reconnect")
                return True

        self._status = IBConnectionStatus.CONNECTING
        logger.info(
            "Connecting to IB %s | %s:%d client_id=%d",
            _broker_label(self._config.port),
            self._config.host,
            self._config.port,
            self._config.client_id,
        )

        try:
            self._ib = IB()
            await asyncio.wait_for(
                self._ib.connectAsync(
                    host=self._config.host,
                    port=self._config.port,
                    clientId=self._config.client_id,
                    readonly=self._config.readonly,
                    account=self._config.account or "",
                ),
                timeout=self._config.timeout,
            )

            self._status = IBConnectionStatus.CONNECTED
            self._connect_time = time.time()
            self._last_error = None

            # Confirm paper account
            managed = self._ib.managedAccounts()
            logger.info(
                "Connected to IB Gateway | paper_account=%s managed=%s",
                self._config.account or "(auto)",
                managed,
            )
            return True

        except asyncio.TimeoutError:
            msg = (
                f"Timeout connecting to IB Gateway at "
                f"{self._config.host}:{self._config.port} "
                f"(waited {self._config.timeout}s) — is Gateway running?"
            )
            logger.error(msg)
            self._status = IBConnectionStatus.ERROR
            self._last_error = msg
            self._ib = None
            return False

        except Exception as exc:
            msg = f"IB Gateway connection failed: {exc}"
            logger.error(msg, exc_info=True)
            self._status = IBConnectionStatus.ERROR
            self._last_error = msg
            self._ib = None
            return False

    async def disconnect(self) -> None:
        """Gracefully disconnect from IB Gateway."""
        if self._ib is not None:
            try:
                self._ib.disconnect()
                logger.info("Disconnected from IB Gateway")
            except Exception as exc:
                logger.warning("Error during IB Gateway disconnect: %s", exc)
            finally:
                self._ib = None
        self._status = IBConnectionStatus.DISCONNECTED
        self._connect_time = None

    async def reconnect(self) -> bool:
        """Disconnect then reconnect. Used by health monitor."""
        logger.info("IBGatewayManager: reconnecting...")
        await self.disconnect()
        await asyncio.sleep(2)
        return await self.connect()

    # ── Status ────────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        """Returns True if the IB session is active and confirmed connected."""
        if self._ib is None or not IB_INSYNC_AVAILABLE:
            return False
        try:
            return self._ib.isConnected()
        except Exception:
            return False

    def get_status(self) -> IBConnectionStatus:
        """Returns the current IBConnectionStatus enum value."""
        # Sync the status with actual socket state when possible
        if self._status == IBConnectionStatus.CONNECTED and not self.is_connected():
            self._status = IBConnectionStatus.ERROR
            logger.warning("IB Gateway connection dropped (detected at get_status)")
        return self._status

    # ── Contract resolution ───────────────────────────────────────────────

    def _resolve_contract(self, symbol: str) -> Optional[object]:
        """
        Build an ib_async Contract for the given JARVIS symbol.

        Supports:
          - Micro-futures from FUTURES_SYMBOL_MAP (MES, MNQ, etc.)
          - Plain equities (fallback — uses SMART routing)
          - Options in format SYMBOL_YYMMDD[C/P]STRIKE

        Returns a Contract object or None if IB is unavailable.
        """
        if not IB_INSYNC_AVAILABLE:
            return None

        upper = symbol.upper()

        # 1. Options Check (e.g. AAPL_260522C190)
        if "_" in upper and any(c in upper for c in ("C", "P")):
            return self._resolve_option_contract(upper)

        # 2. Futures Check
        if upper in FUTURES_SYMBOL_MAP:
            spec = FUTURES_SYMBOL_MAP[upper]
            if upper == "MCL":
                contract_month = _nearest_front_month()
            else:
                contract_month = _nearest_quarterly_expiry()

            contract = Future(
                symbol=spec["underlying"],
                lastTradeDateOrContractMonth=contract_month,
                exchange=spec["exchange"],
                currency=spec["currency"],
                multiplier=spec["multiplier"],
            )
            logger.debug(
                "Resolved %s → Future(%s, %s, month=%s)",
                symbol,
                spec["underlying"],
                spec["exchange"],
                contract_month,
            )
            return contract

        # 3. Generic equity fallback
        contract = Stock(symbol=upper, exchange="SMART", currency="USD")
        logger.debug("Resolved %s → Stock(SMART)", symbol)
        return contract

    def _resolve_option_contract(self, symbol: str) -> Optional[Option]:
        """
        Parse an option symbol (e.g. AAPL_260522C190) into an Option contract.
        """
        try:
            # Format: UNDERLYING_YYMMDDCSTRIKE
            parts = symbol.split("_")
            underlying = parts[0]
            rest = parts[1]

            # Find C or P index
            right_idx = rest.find("C")
            if right_idx == -1:
                right_idx = rest.find("P")

            if right_idx == -1:
                return None

            expiry = "20" + rest[:right_idx]  # 260522 -> 20260522
            right = rest[right_idx]  # C or P
            strike = float(rest[right_idx + 1 :])

            return Option(
                symbol=underlying,
                lastTradeDateOrContractMonth=expiry,
                strike=strike,
                right=right,
                exchange="SMART",
                currency="USD",
            )
        except Exception as exc:
            logger.warning("Failed to resolve option contract for %s: %s", symbol, exc)
            return None

    async def get_options_greeks(self, symbol: str) -> dict:
        """
        Fetch real-time Greeks for a specific option symbol.
        """
        if self._ib is None or not self.is_connected():
            return {"error": "Not connected"}

        contract = self._resolve_contract(symbol)
        if not contract or not isinstance(contract, Option):
            return {"error": f"Invalid option symbol: {symbol}"}

        qualified = await self._qualify_contract(contract)
        if not qualified:
            return {"error": f"Could not qualify contract: {symbol}"}

        try:
            # Request market data for Greeks
            # We use snapshotted data for one-off requests
            ticker = self._ib.reqMktData(qualified, "100,101,104,106", snapshot=True)

            # Wait for data to populate (max 5s)
            t0 = time.monotonic()
            while time.monotonic() - t0 < 5.0:
                if ticker.modelGreeks is not None:
                    break
                await asyncio.sleep(0.1)

            greeks = ticker.modelGreeks
            if greeks is None:
                # Fallback to marketGreeks if model is unavailable
                greeks = ticker.marketGreeks

            if greeks is None:
                return {"error": "Greeks unavailable for this contract", "symbol": symbol}

            return {
                "symbol": symbol,
                "delta": greeks.delta,
                "gamma": greeks.gamma,
                "theta": greeks.theta,
                "vega": greeks.vega,
                "implied_vol": greeks.impliedVol,
                "und_price": greeks.undPrice,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            logger.error("get_options_greeks failed for %s: %s", symbol, exc)
            return {"error": str(exc)}

    async def _qualify_contract(self, contract) -> Optional[object]:
        """
        Ask IB to qualify (fill in conId, exchange, etc.) a contract.
        Returns the qualified contract or None on failure.
        """
        if self._ib is None or not self.is_connected():
            logger.error("_qualify_contract: not connected")
            return None
        try:
            qualified = await self._ib.qualifyContractsAsync(contract)
            if not qualified:
                logger.error("_qualify_contract: IB returned empty list for %s", contract)
                return None
            return qualified[0]
        except Exception as exc:
            logger.error("_qualify_contract failed for %s: %s", contract, exc)
            return None

    # ── Order placement ───────────────────────────────────────────────────

    def _validate_order_preconditions(
        self, action: str, quantity: int
    ) -> Optional[tuple[str, str]]:
        """Validate safety and input preconditions. Returns (action_upper, order_type_upper) or None."""
        if self._config.port in LIVE_TRADING_PORTS:
            logger.critical(
                "place_paper_order: port %d rejected — live trading disabled",
                self._config.port,
            )
            return None
        if not IB_INSYNC_AVAILABLE:
            logger.error("place_paper_order: ib_async not installed")
            return None
        if not self.is_connected():
            logger.error("place_paper_order: not connected to IB Gateway. Call connect() first.")
            return None
        action_upper = action.upper()
        if action_upper not in ("BUY", "SELL"):
            logger.error("place_paper_order: invalid action '%s' — must be BUY or SELL", action)
            return None
        if quantity <= 0:
            logger.error("place_paper_order: quantity must be positive, got %d", quantity)
            return None
        return action_upper

    def _build_order_object(
        self,
        order_type_upper: str,
        action_upper: str,
        quantity: int,
        limit_price: Optional[float],
        aux_price: Optional[float],
        order_ref: Optional[str] = None,
    ) -> Optional[object]:
        """Build appropriate IB order object. Returns order or None.

        ``order_ref``, when provided, is set as the IB ``orderRef`` tag so that
        JARVIS-originated fills can be distinguished from the paper account's
        pre-seeded demo activity (DUP662235 carries demo positions) during
        reconciliation — see ``ibkr_reconciler`` / the execution-fidelity gate.
        """
        order: Optional[object]
        if order_type_upper == "MKT":
            order = MarketOrder(action=action_upper, totalQuantity=quantity)
        elif order_type_upper == "LMT":
            if limit_price is None:
                logger.error("place_paper_order: limit_price required for LMT order")
                return None
            order = LimitOrder(
                action=action_upper,
                totalQuantity=quantity,
                lmtPrice=limit_price,
            )
        elif order_type_upper == "STP":
            if aux_price is None:
                logger.error("place_paper_order: aux_price (stop price) required for STP order")
                return None
            order = StopOrder(
                action=action_upper,
                totalQuantity=quantity,
                stopPrice=aux_price,
            )
        elif order_type_upper in ("STP_LMT", "STPLMT"):
            if aux_price is None or limit_price is None:
                logger.error(
                    "place_paper_order: both aux_price and limit_price required for STP_LMT"
                )
                return None
            order = StopLimitOrder(
                action=action_upper,
                totalQuantity=quantity,
                lmtPrice=limit_price,
                stopPrice=aux_price,
            )
        else:
            logger.error("place_paper_order: unsupported order_type '%s'", order_type_upper)
            return None

        if order_ref:
            order.orderRef = order_ref
        return order

    async def place_paper_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
        aux_price: Optional[float] = None,
        parent_order_id: Optional[int] = None,
        order_ref: Optional[str] = None,
    ) -> Optional[int]:
        """
        Place an order on the IB paper account (port 4002 only).

        Args:
            symbol:          JARVIS symbol (e.g. "MES", "MNQ", "AAPL")
            action:          "BUY" or "SELL"
            quantity:        Number of contracts / shares (positive integer)
            order_type:      "MKT", "LMT", "STP", "STP_LMT"
            limit_price:     Required for LMT and STP_LMT orders
            aux_price:       Stop price for STP and STP_LMT orders
            parent_order_id: IB orderId of the parent entry when placing a
                             child STP — sets Order.parentId so IB links the
                             child to the entry fill atomically at the broker.
            order_ref:       IB ``orderRef`` tag. Defaults to a generated
                             ``JARVIS-<uuid>`` so every JARVIS-routed fill is
                             distinguishable from the account's pre-seeded demo
                             activity during reconciliation. Pass an explicit
                             value to link related orders (e.g. entry + child).

        Returns:
            IB order ID (int) on success, None on failure.
        """
        action_upper = self._validate_order_preconditions(action, quantity)
        if action_upper is None:
            return None

        order_type_upper = order_type.upper()

        # Tag every JARVIS-routed order so reconciliation can filter our fills
        # out of the demo-seed portfolio. Inert until ALLOW_PAPER_SIMULATED_ORDERS
        # is enabled (this real-IB path is only used when the flag is True).
        if order_ref is None:
            order_ref = f"JARVIS-{uuid.uuid4().hex[:12]}"

        logger.info(
            "place_paper_order | symbol=%s action=%s qty=%d type=%s lmt=%s aux=%s parent=%s ref=%s",
            symbol,
            action_upper,
            quantity,
            order_type_upper,
            limit_price,
            aux_price,
            parent_order_id,
            order_ref,
        )

        try:
            contract = self._resolve_contract(symbol)
            if contract is None:
                logger.error("place_paper_order: could not resolve contract for %s", symbol)
                return None

            contract = await self._qualify_contract(contract)
            if contract is None:
                logger.error("place_paper_order: could not qualify contract for %s", symbol)
                return None

            ib_order = self._build_order_object(
                order_type_upper, action_upper, quantity, limit_price, aux_price,
                order_ref=order_ref,
            )
            if ib_order is None:
                return None

            if self._config.account:
                ib_order.account = self._config.account

            if parent_order_id is not None:
                ib_order.parentId = int(parent_order_id)

            trade = self._ib.placeOrder(contract, ib_order)
            order_id: int = trade.order.orderId

            logger.info(
                "Order placed | symbol=%s action=%s qty=%d type=%s order_id=%d parent=%s ref=%s",
                symbol,
                action_upper,
                quantity,
                order_type_upper,
                order_id,
                parent_order_id,
                order_ref,
            )
            return order_id

        except Exception as exc:
            logger.error(
                "place_paper_order failed | symbol=%s action=%s qty=%d: %s",
                symbol,
                action,
                quantity,
                exc,
                exc_info=True,
            )
            return None

    async def place_bracket_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        entry_type: str = "MKT",
        limit_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> dict:
        """Place a native IB bracket: entry + OCA-linked stop-loss + take-profit.

        Drop-in replacement for ``IBGatewayConnector.place_bracket_order`` — same
        signature and same return contract — but this routes a REAL broker-side
        bracket so the stop actually rests at IB (survives an engine restart),
        which the in-process simulator can never do.

        Atomicity via transmit sequencing: the parent entry is placed with
        ``transmit=False`` and only the LAST leg placed carries ``transmit=True``,
        so IB releases all legs as one group. Because the parent stays
        un-transmitted until the final child is accepted, there is no window in
        which the entry can fill without its stop already staged — a mid-sequence
        failure leaves nothing resting (the opposite of the immediate-transmit
        ``submit_bracket`` path, which needs a rollback-cancel to close a naked
        position). The two children share an OCA group (``ocaType=1``) so a fill
        on one cancels the other, and both carry ``parentId=<entry orderId>`` so
        ``get_order_status`` / ``SafetyLayer._verify_parent_linkage`` confirm the
        broker-side linkage.

        Returns the connector's exact dict shape:
            success -> {"status":"placed","entry_id","sl_id","tp_id",
                        "symbol","action","quantity"}   (sl_id/tp_id may be None)
            failure -> {"status":"error","error": <reason>}

        Registry / DB / migration-031 writes are intentionally NOT done here — the
        simulator does none either; those live in ``brokers.bracket_orders``.
        """
        if not self.is_connected():
            return {"status": "error", "error": "Not connected"}

        action_upper = self._validate_order_preconditions(action, quantity)
        if action_upper is None:
            return {"status": "error", "error": "Failed to place entry order"}

        # Normalise entry type. entry_type arrives lowercased from the safety
        # layer (req.order_type = order_type.lower()); alias MARKET/LIMIT so the
        # exact-match _build_order_object accepts it.
        entry_type_upper = entry_type.upper()
        entry_type_upper = {"MARKET": "MKT", "LIMIT": "LMT"}.get(
            entry_type_upper, entry_type_upper
        )
        if entry_type_upper not in ("MKT", "LMT"):
            logger.error("place_bracket_order: unsupported entry_type '%s'", entry_type)
            return {"status": "error", "error": "Failed to place entry order"}

        exit_action = "SELL" if action_upper == "BUY" else "BUY"
        want_sl = stop_loss is not None
        want_tp = take_profit is not None
        has_children = want_sl or want_tp
        # Shared reconciliation tag + unique OCA group for this bracket.
        order_ref = f"JARVIS-{uuid.uuid4().hex[:12]}"
        oca_group = f"JARVIS-OCA-{uuid.uuid4().hex[:12]}"

        placed_trades: list = []
        try:
            contract = self._resolve_contract(symbol)
            if contract is None:
                logger.error("place_bracket_order: could not resolve contract for %s", symbol)
                return {"status": "error", "error": "Failed to place entry order"}
            contract = await self._qualify_contract(contract)
            if contract is None:
                logger.error("place_bracket_order: could not qualify contract for %s", symbol)
                return {"status": "error", "error": "Failed to place entry order"}

            # Parent entry. transmit=False while children follow (atomic bundle).
            parent = self._build_order_object(
                entry_type_upper, action_upper, quantity, limit_price, None,
                order_ref=order_ref,
            )
            if parent is None:
                return {"status": "error", "error": "Failed to place entry order"}
            if self._config.account:
                parent.account = self._config.account
            parent.transmit = not has_children
            parent_trade = self._ib.placeOrder(contract, parent)
            placed_trades.append(parent_trade)
            entry_id = int(parent_trade.order.orderId)

            # Children: SL then TP; the LAST leg placed carries transmit=True to
            # release the whole bracket at the broker.
            child_specs = []
            if want_sl:
                child_specs.append(("STP", None, stop_loss))
            if want_tp:
                child_specs.append(("LMT", take_profit, None))

            sl_id = None
            tp_id = None
            for idx, (otype, lmt, aux) in enumerate(child_specs):
                child = self._build_order_object(
                    otype, exit_action, quantity, lmt, aux, order_ref=order_ref,
                )
                if child is None:
                    raise RuntimeError(f"failed to build {otype} child order")
                if self._config.account:
                    child.account = self._config.account
                child.parentId = entry_id
                child.ocaGroup = oca_group
                child.ocaType = 1
                child.transmit = idx == len(child_specs) - 1
                child_trade = self._ib.placeOrder(contract, child)
                placed_trades.append(child_trade)
                child_id = int(child_trade.order.orderId)
                if otype == "STP":
                    sl_id = child_id
                else:
                    tp_id = child_id

            logger.info(
                "place_bracket_order placed | symbol=%s entry=%d sl=%s tp=%s ref=%s oca=%s",
                symbol, entry_id, sl_id, tp_id, order_ref, oca_group,
            )
            return {
                "status": "placed",
                "entry_id": entry_id,
                "sl_id": sl_id,
                "tp_id": tp_id,
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
            }

        except Exception as exc:
            if not placed_trades:
                logger.error(
                    "place_bracket_order: entry failed symbol=%s: %s",
                    symbol, exc, exc_info=True,
                )
                return {"status": "error", "error": "Failed to place entry order"}
            # A child leg failed AFTER the parent was placed. Every leg so far is
            # transmit=False -> none is live -> no naked position. Best-effort
            # cancel the un-transmitted legs, then surface the failure.
            logger.critical(
                "place_bracket_order: child leg failed symbol=%s — rolling back "
                "%d un-transmitted leg(s): %s",
                symbol, len(placed_trades), exc, exc_info=True,
            )
            for tr in reversed(placed_trades):
                try:
                    self._ib.cancelOrder(tr.order)
                except Exception as cexc:
                    logger.critical(
                        "place_bracket_order: rollback cancel FAILED id=%s: %s",
                        getattr(getattr(tr, "order", None), "orderId", "?"), cexc,
                    )
            return {"status": "error", "error": "Failed to place bracket child order"}

    async def cancel_order(self, order_id: int) -> bool:
        """
        Cancel an open IB order by order ID.

        Returns True if cancellation was sent, False otherwise.
        Note: IB cancel is fire-and-forget; check get_open_orders() to confirm.
        """
        if not IB_INSYNC_AVAILABLE or not self.is_connected():
            logger.error("cancel_order: not connected or library missing")
            return False

        try:
            open_trades = self._ib.openTrades()
            target = None
            for trade in open_trades:
                if trade.order.orderId == order_id:
                    target = trade
                    break

            if target is None:
                logger.warning("cancel_order: order_id=%d not found in open trades", order_id)
                return False

            self._ib.cancelOrder(target.order)
            logger.info("cancel_order: sent cancel for order_id=%d", order_id)
            return True

        except Exception as exc:
            logger.error("cancel_order failed for order_id=%d: %s", order_id, exc, exc_info=True)
            return False

    # ── Open orders ───────────────────────────────────────────────────────

    async def get_open_orders(self) -> list[dict]:
        """
        Return all open orders as a list of dicts.

        Each dict contains:
          order_id, parent_id, symbol, action, quantity, order_type,
          limit_price, aux_price, status, filled, remaining
        """
        if not IB_INSYNC_AVAILABLE or not self.is_connected():
            logger.warning("get_open_orders: not connected")
            return []

        try:
            await self._ib.reqAllOpenOrdersAsync()
            trades = self._ib.openTrades()
            result = []
            for trade in trades:
                order = trade.order
                status = trade.orderStatus
                contract = trade.contract
                result.append(
                    {
                        "order_id": order.orderId,
                        "parent_id": getattr(order, "parentId", 0) or None,
                        "symbol": contract.symbol,
                        "action": order.action,
                        "quantity": order.totalQuantity,
                        "order_type": order.orderType,
                        "limit_price": getattr(order, "lmtPrice", None),
                        "aux_price": getattr(order, "auxPrice", None),
                        "status": status.status,
                        "filled": status.filled,
                        "remaining": status.remaining,
                        "avg_fill_price": status.avgFillPrice,
                    }
                )
            return result

        except Exception as exc:
            logger.error("get_open_orders failed: %s", exc, exc_info=True)
            return []

    async def get_order_status(self, order_id: str) -> dict:
        """Return status dict for a single order, including parent_order_id.

        Used by SafetyLayer._verify_parent_linkage to confirm broker-side
        STP/TP children carry the correct parentId before reporting stp_linked.
        """
        orders = await self.get_open_orders()
        for o in orders:
            if str(o.get("order_id")) == str(order_id):
                return {
                    "order_id": o["order_id"],
                    "parent_order_id": o.get("parent_id"),
                    "status": o.get("status"),
                    "symbol": o.get("symbol"),
                }
        return {}

    # ── Account summary ───────────────────────────────────────────────────

    async def get_account_summary(self) -> dict:
        """
        Return key account metrics from IB.

        Dict keys: NetLiquidation, TotalCashValue, UnrealizedPnL, RealizedPnL
        Values are floats; missing fields default to 0.0.
        Returns an empty dict on failure.
        """
        if not IB_INSYNC_AVAILABLE or not self.is_connected():
            logger.warning("get_account_summary: not connected")
            return {}

        try:
            account_values = await self._ib.accountSummaryAsync(account=self._config.account or "")

            KEYS_OF_INTEREST = {
                "NetLiquidation",
                "TotalCashValue",
                "UnrealizedPnL",
                "RealizedPnL",
                "GrossPositionValue",
                "MaintMarginReq",
                "InitMarginReq",
                "AvailableFunds",
                "BuyingPower",
            }

            summary: dict = dict.fromkeys(KEYS_OF_INTEREST, 0.0)
            for av in account_values:
                if av.tag in KEYS_OF_INTEREST:
                    try:
                        summary[av.tag] = float(av.value)
                    except (ValueError, TypeError):
                        pass

            # Convenience alias used by SafetyLayer / OrderRouter
            summary["equity"] = summary["NetLiquidation"]
            return summary

        except Exception as exc:
            logger.error("get_account_summary failed: %s", exc, exc_info=True)
            return {}

    # ── Positions ─────────────────────────────────────────────────────────

    async def get_positions(self) -> list[dict]:
        """
        Return current IB positions as a list of dicts.

        Each dict contains:
          symbol, secType, exchange, currency,
          position (signed int), avg_cost, market_price, market_value, unrealized_pnl
        """
        if not IB_INSYNC_AVAILABLE or not self.is_connected():
            logger.warning("get_positions: not connected")
            return []

        try:
            positions = await self._ib.reqPositionsAsync()
            result = []
            for pos in positions:
                contract = pos.contract
                result.append(
                    {
                        "symbol": contract.symbol,
                        "sec_type": contract.secType,
                        "exchange": getattr(contract, "exchange", ""),
                        "currency": contract.currency,
                        "position": pos.position,
                        "avg_cost": pos.avgCost,
                        "market_price": None,  # Requires market data subscription
                        "market_value": None,  # Populate via portfolio items if needed
                        "unrealized_pnl": None,
                        "account": pos.account,
                    }
                )
            return result

        except Exception as exc:
            logger.error("get_positions failed: %s", exc, exc_info=True)
            return []

    async def get_portfolio_value(self) -> float:
        """
        Return current portfolio NetLiquidation value as a float.
        Returns 0.0 on failure.
        """
        summary = await self.get_account_summary()
        return float(summary.get("NetLiquidation", 0.0))

    async def get_executions(self) -> list[dict]:
        """
        Return recent IB execution fills as a list of dicts.

        Calls reqExecutionsAsync() with no filter to fetch all fills from the
        current and recent sessions (IB typically surfaces the current day +
        prior session fills while the session is live).

        Each dict: exec_id, account, symbol, sec_type, expiry, side (BOT/SLD),
        quantity, price, avg_price, commission, exchange, currency, fill_time,
        order_id, order_ref.

        ``order_ref`` carries the IB orderRef stamped by place_paper_order
        (JARVIS-<uuid>), letting the reconciler distinguish JARVIS-originated
        fills from the DUP662235 demo-seed activity.
        """
        if not IB_INSYNC_AVAILABLE or not self.is_connected():
            logger.warning("get_executions: not connected")
            return []

        try:
            fills = await self._ib.reqExecutionsAsync()
            result = []
            for fill in fills:
                contract = fill.contract
                execution = fill.execution
                commission_report = fill.commissionReport
                result.append(
                    {
                        "exec_id": execution.execId,
                        "account": execution.acctNumber,
                        "symbol": contract.symbol,
                        "sec_type": contract.secType,
                        "expiry": getattr(contract, "lastTradeDateOrContractMonth", ""),
                        "side": execution.side,  # "BOT" or "SLD"
                        "quantity": execution.shares,
                        "price": execution.price,
                        "avg_price": execution.avgPrice,
                        "commission": getattr(commission_report, "commission", None),
                        "exchange": execution.exchange,
                        "currency": contract.currency,
                        "fill_time": str(execution.time),
                        "order_id": execution.orderId,
                        "order_ref": getattr(execution, "orderRef", "") or "",
                    }
                )
            return result

        except Exception as exc:
            logger.error("get_executions failed: %s", exc, exc_info=True)
            return []

    # ── Health check ──────────────────────────────────────────────────────

    async def health_check(self) -> dict:
        """
        Return a health-check dict suitable for /api/health endpoints.

        Keys:
          connected       (bool)
          status          (str — IBConnectionStatus.value)
          port            (int)
          account         (str)
          uptime_seconds  (float | None)
          latency_ms      (float | None)
          net_liquidation (float)
          open_orders     (int)
          last_error      (str | None)
          ib_library      (str)
        """
        start = time.monotonic()

        connected = self.is_connected()
        latency_ms: Optional[float] = None
        net_liq: float = 0.0
        open_order_count: int = 0

        if connected:
            # Measure round-trip latency with a lightweight reqCurrentTime call
            try:
                t0 = time.monotonic()
                await asyncio.wait_for(self._ib.reqCurrentTimeAsync(), timeout=5.0)
                latency_ms = (time.monotonic() - t0) * 1000
            except Exception:
                latency_ms = None

            try:
                net_liq = await self.get_portfolio_value()
            except Exception:
                pass

            try:
                orders = await self.get_open_orders()
                open_order_count = len(orders)
            except Exception:
                pass

        uptime: Optional[float] = None
        if self._connect_time is not None:
            uptime = time.time() - self._connect_time

        # Determine library name for transparency
        lib_name = "ib_async" if IB_INSYNC_AVAILABLE else "not_installed"

        result = {
            "connected": connected,
            "status": self.get_status().value,
            "port": self._config.port,
            "host": self._config.host,
            "account": self._config.account or "(auto-detect)",
            "uptime_seconds": uptime,
            "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
            "net_liquidation": net_liq,
            "open_orders": open_order_count,
            "last_error": self._last_error,
            "ib_library": lib_name,
            "paper_trading_only": True,  # SAFETY: always True — port 4001 is disabled
        }

        elapsed = (time.monotonic() - start) * 1000
        logger.debug("health_check completed in %.1f ms | connected=%s", elapsed, connected)
        return result

    # ── Context manager support ───────────────────────────────────────────

    async def __aenter__(self) -> "IBGatewayManager":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    # ── Repr ──────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"IBGatewayManager("
            f"host={self._config.host!r}, "
            f"port={self._config.port}, "
            f"status={self._status.value}, "
            f"account={self._config.account!r})"
        )
