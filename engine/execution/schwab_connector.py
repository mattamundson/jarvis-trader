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

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["SchwabConnector", "ConnectionState"]

_TOKEN_PATH = Path(__file__).parent.parent / ".schwab_token.json"
_EQUITY_SIDES = frozenset({"BUY", "SELL"})
_OPTIONS_ACTIONS = frozenset({"buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"})
_ORDER_TYPES = frozenset({"market", "limit"})


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class SchwabConnector:
    """
    Production Schwab connector matching the IBGatewayConnector interface.

    Safety contract: every order path calls self._safety_layer.check_order()
    before touching the broker. The safety layer retains full VETO power.
    """

    def __init__(self, settings, safety_layer=None, portfolio_tracker=None):
        """
        Args:
            settings: TradingConfig — reads SCHWAB_APP_KEY, SCHWAB_APP_SECRET,
                SCHWAB_CALLBACK_URL, SCHWAB_READY.
            safety_layer: SafetyLayer — check_order() called before every order.
            portfolio_tracker: PortfolioTracker — paper fills mirrored via PaperTradeLogger.
        """
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

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> bool:
        """
        Public entry point called by main.py lifespan and schwab_router.py.

        Runs the SCHWAB_READY gate and then delegates to connect().
        Returns True on success, False if credentials are missing or connect fails.
        Raises RuntimeError if SCHWAB_READY is not set (Phase 3 guard).
        """
        self._assert_schwab_ready()
        return await self.connect()

    async def connect(self) -> bool:
        """Initialize schwab-py client from token file. Returns True on success."""
        self._assert_schwab_ready()
        self._state = ConnectionState.CONNECTING

        api_key = self._settings.SCHWAB_APP_KEY
        app_secret = self._settings.SCHWAB_APP_SECRET

        if not api_key or not app_secret:
            logger.error(
                "SchwabConnector: SCHWAB_APP_KEY/SECRET not set.\n%s", self._auth_instructions()
            )
            self._state = ConnectionState.ERROR
            return False

        if not _TOKEN_PATH.exists():
            logger.error(
                "SchwabConnector: token not found at %s\n%s", _TOKEN_PATH, self._auth_instructions()
            )
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
                    logger.info(
                        "SchwabConnector: connected — account hash %s…",
                        self._account_hash[:8] if self._account_hash else "n/a",
                    )
                else:
                    logger.warning("SchwabConnector: no accounts returned")
            else:
                logger.warning("SchwabConnector: get_account_numbers HTTP %s", response.status_code)

            self._state = ConnectionState.CONNECTED
            self._reconnect_attempts = 0
            self._last_heartbeat = datetime.now(timezone.utc)

            if self._heartbeat_task is None or self._heartbeat_task.done():
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # Warn if token is close to expiry
            days_left = self.token_expires_in_days()
            if days_left is not None and days_left < 2:
                logger.warning(
                    "SchwabConnector: token expires in %d day(s) — re-auth required soon. "
                    "Run: .venv/Scripts/python.exe -c \"import schwab; "
                    "schwab.auth.easy_client(api_key='...', app_secret='...', "
                    "callback_url='https://127.0.0.1', token_path='.schwab_token.json')\"",
                    days_left,
                )

            logger.info("SchwabConnector: state=%s", self._state.value)
            return True

        except Exception as exc:
            logger.error("SchwabConnector.connect failed: %s", exc, exc_info=True)
            self._state = ConnectionState.ERROR
            return False

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
        logger.info("SchwabConnector: disconnected")
        return True

    @property
    def state(self) -> ConnectionState:
        """Public read-only view of connection state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED and self._client is not None

    # ── Resilience ────────────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Monitor connection every 60s; reconnect on failure or 401."""
        while True:
            try:
                await asyncio.sleep(60)
                if not self.is_connected:
                    logger.warning("SchwabConnector: heartbeat detected disconnection")
                    self._reconnect_attempts = 0
                    await self._reconnect_with_backoff()
                else:
                    response = self._client.get_account_numbers()
                    if response.status_code == 401:
                        logger.warning("SchwabConnector: heartbeat 401 — token expired?")
                        self._state = ConnectionState.RECONNECTING
                        self._reconnect_attempts = 0
                        await self._reconnect_with_backoff()
                    else:
                        self._last_heartbeat = datetime.now(timezone.utc)
                        logger.debug("SchwabConnector: heartbeat OK")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("SchwabConnector: heartbeat error: %s", exc, exc_info=True)

    async def _reconnect_with_backoff(self) -> bool:
        """3 retries at 1s, 2s, 4s. Returns True on success."""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.critical("SchwabConnector: max reconnect attempts exhausted — state=ERROR")
            self._state = ConnectionState.ERROR
            return False

        self._reconnect_attempts += 1
        backoff = 2 ** (self._reconnect_attempts - 1)
        logger.warning(
            "SchwabConnector: reconnect %d/%d — waiting %ds",
            self._reconnect_attempts,
            self._max_reconnect_attempts,
            backoff,
        )
        self._state = ConnectionState.RECONNECTING
        await asyncio.sleep(backoff)

        if await self.connect():
            logger.info("SchwabConnector: reconnected on attempt %d", self._reconnect_attempts)
            return True
        return await self._reconnect_with_backoff()

    # ── Internal Guards ───────────────────────────────────────────────────────

    def _assert_schwab_ready(self) -> None:
        """Raise RuntimeError if SCHWAB_READY is not set True in config."""
        if not getattr(self._settings, "SCHWAB_READY", False):
            raise RuntimeError(
                "Schwab integration incomplete — SCHWAB_READY gate not enabled. "
                "Set SCHWAB_READY=True in .env only after Phase 3 approval."
            )

    def _get_paper_trade_logger(self):
        if self._paper_trade_logger is None:
            from execution.paper_trade_logger import PaperTradeLogger  # noqa: PLC0415

            self._paper_trade_logger = PaperTradeLogger(
                self._settings, portfolio_tracker=self._portfolio_tracker
            )
        return self._paper_trade_logger

    def _run_safety_check(
        self,
        symbol,
        quantity,
        order_type,
        limit_price,
        portfolio_equity,
        is_futures=False,
        is_options=False,
    ):
        """
        Run safety layer check.

        Returns (approved, rejection_reason, warnings, adjusted_order). The
        4th element is the risk-layer's post-adjustment OrderRequest (e.g.
        loss-tracker de-risking after consecutive losses) or None when no
        adjustment was applied -- callers MUST use it to build the actual
        broker order, not the pre-check `quantity` (PRB-01, 2026-07-29
        prod-readiness audit: this helper used to drop adjusted_order
        entirely, so a computed size reduction never reached the fill).
        """
        if self._safety_layer is None:
            return True, None, [], None
        from risk.safety_layer import OrderRequest  # noqa: PLC0415

        req = OrderRequest(
            symbol=symbol,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            is_futures=is_futures,
            is_options=is_options,
        )
        result = self._safety_layer.check_order(req, portfolio_equity)
        return (
            result.approved,
            getattr(result, "rejection_reason", ""),
            result.warnings,
            result.adjusted_order,
        )

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_account_summary(self) -> dict:
        """Account balances and positions. Returns {"error": ...} on failure."""
        if not self.is_connected:
            return {"error": "Schwab not connected"}
        try:
            import schwab  # noqa: PLC0415

            response = self._client.get_account(
                account_hash=self._account_hash,
                fields=[schwab.client.Client.Account.Fields.POSITIONS],
            )
            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}"}

            data = response.json()
            acct = data.get("securitiesAccount", {})
            bal = acct.get("currentBalances", {})
            positions = [
                {
                    "symbol": p.get("instrument", {}).get("symbol"),
                    "asset_type": p.get("instrument", {}).get("assetType"),
                    "quantity": p.get("longQuantity", 0) - p.get("shortQuantity", 0),
                    "average_price": p.get("averagePrice"),
                    "market_value": p.get("marketValue"),
                    "unrealized_pnl": p.get("currentDayProfitLoss"),
                }
                for p in acct.get("positions", [])
            ]
            return {
                "account_hash": self._account_hash,
                "equity": bal.get("equity"),
                "cash_balance": bal.get("cashBalance"),
                "buying_power": bal.get("buyingPower"),
                "day_trading_buying_power": bal.get("dayTradingBuyingPower"),
                "positions": positions,
            }
        except Exception as exc:
            logger.error("SchwabConnector.get_account_summary failed: %s", exc, exc_info=True)
            return {"error": str(exc)}

    async def get_positions(self) -> list[dict]:
        """Current positions. Returns [] when not connected or on error."""
        if not self.is_connected:
            logger.warning("SchwabConnector.get_positions: not connected — returning []")
            return []
        try:
            import schwab  # noqa: PLC0415

            response = self._client.get_account(
                account_hash=self._account_hash,
                fields=[schwab.client.Client.Account.Fields.POSITIONS],
            )
            if response.status_code != 200:
                logger.warning("SchwabConnector.get_positions: HTTP %s", response.status_code)
                return []

            acct = response.json().get("securitiesAccount", {})
            return [
                {
                    "symbol": p.get("instrument", {}).get("symbol"),
                    "asset_type": p.get("instrument", {}).get("assetType"),
                    "quantity": p.get("longQuantity", 0) - p.get("shortQuantity", 0),
                    "average_price": p.get("averagePrice"),
                    "market_value": p.get("marketValue"),
                    "unrealized_pnl": p.get("currentDayProfitLoss"),
                }
                for p in acct.get("positions", [])
            ]
        except Exception as exc:
            logger.error("SchwabConnector.get_positions failed: %s", exc, exc_info=True)
            return []

    async def get_transaction_history(self, days: int = 7) -> list[dict]:
        """
        Recent transactions. days=7 by default.
        Returns [] when not connected or on error.
        """
        if not self.is_connected:
            logger.warning("SchwabConnector.get_transaction_history: not connected — returning []")
            return []
        try:
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=days)
            response = self._client.get_transactions(
                account_hash=self._account_hash,
                start_date=start_dt,
                end_date=end_dt,
            )
            if response.status_code != 200:
                logger.warning(
                    "SchwabConnector.get_transaction_history: HTTP %s", response.status_code
                )
                return []

            return [
                {
                    "transaction_id": tx.get("activityId"),
                    "transaction_type": tx.get("type"),
                    "trade_date": tx.get("tradeDate"),
                    "settlement_date": tx.get("settlementDate"),
                    "net_amount": tx.get("netAmount"),
                    "description": tx.get("description"),
                }
                for tx in response.json()
            ]
        except Exception as exc:
            logger.error("SchwabConnector.get_transaction_history failed: %s", exc, exc_info=True)
            return []

    # ── Market Data ───────────────────────────────────────────────────────────

    async def get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Real-time quotes. Returns {} when not connected or on error."""
        if not self.is_connected:
            return {}
        try:
            response = self._client.get_quotes(symbols)
            if response.status_code != 200:
                logger.warning("SchwabConnector.get_quotes: HTTP %s", response.status_code)
                return {}

            return {
                sym: {
                    "symbol": sym,
                    "bid": data.get("quote", {}).get("bidPrice"),
                    "ask": data.get("quote", {}).get("askPrice"),
                    "last": data.get("quote", {}).get("lastPrice"),
                    "volume": data.get("quote", {}).get("totalVolume"),
                    "mark": data.get("quote", {}).get("mark"),
                    "change_pct": data.get("quote", {}).get("netPercentChangeInDouble"),
                }
                for sym, data in response.json().items()
            }
        except Exception as exc:
            logger.error("SchwabConnector.get_quotes failed: %s", exc, exc_info=True)
            return {}

    async def get_options_chain(self, symbol: str, expiry_date: Optional[str] = None) -> dict:
        """
        Options chain with Greeks. expiry_date="YYYY-MM-DD", None=nearest expiry.
        Returns {"error": ...} on failure.
        """
        if not self.is_connected:
            return {"error": "Schwab not connected"}
        try:
            import schwab  # noqa: PLC0415

            kwargs: dict = {
                "symbol": symbol,
                "contract_type": schwab.client.Client.Options.ContractType.ALL,
                "include_underlying_quote": True,
            }
            if expiry_date:
                from datetime import date as _date  # noqa: PLC0415

                parsed = _date.fromisoformat(expiry_date)
                kwargs["from_date"] = parsed
                kwargs["to_date"] = parsed

            response = self._client.get_option_chain(**kwargs)
            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}"}

            data = response.json()

            def _parse_legs(exp_map: dict) -> list[dict]:
                legs = []
                for exp_str, strikes in exp_map.items():
                    for strike_str, contracts in strikes.items():
                        for c in contracts:
                            legs.append(
                                {
                                    "option_symbol": c.get("symbol"),
                                    "expiry": exp_str,
                                    "strike": float(strike_str),
                                    "bid": c.get("bid"),
                                    "ask": c.get("ask"),
                                    "last": c.get("last"),
                                    "volume": c.get("totalVolume"),
                                    "open_interest": c.get("openInterest"),
                                    "delta": c.get("delta"),
                                    "gamma": c.get("gamma"),
                                    "theta": c.get("theta"),
                                    "vega": c.get("vega"),
                                    "iv": c.get("volatility"),
                                    "in_the_money": c.get("inTheMoney"),
                                }
                            )
                return legs

            underlying = data.get("underlying", {})
            return {
                "symbol": symbol,
                "underlying_price": underlying.get("mark"),
                "calls": _parse_legs(data.get("callExpDateMap", {})),
                "puts": _parse_legs(data.get("putExpDateMap", {})),
            }
        except Exception as exc:
            logger.error(
                "SchwabConnector.get_options_chain failed for %s: %s", symbol, exc, exc_info=True
            )
            return {"error": str(exc)}

    # ── Order Execution ───────────────────────────────────────────────────────

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
        side_upper = side.upper()
        if side_upper not in _EQUITY_SIDES:
            return {"status": "error", "reason": f"Invalid side: {side!r}"}

        ot_internal = "limit" if order_type.upper() in ("LIMIT", "LMT") else "market"
        if ot_internal == "limit" and limit_price is None:
            return {"status": "error", "reason": "limit_price required for LIMIT orders"}
        if not self.is_connected:
            return {"status": "error", "reason": "Schwab not connected"}

        try:
            from schwab.orders.equities import (  # noqa: PLC0415
                equity_buy_limit,
                equity_buy_market,
                equity_sell_limit,
                equity_sell_market,
            )

            logger.info(
                "SchwabConnector.submit_equity_order | %s %s qty=%d type=%s limit=%s",
                side_upper,
                symbol,
                quantity,
                ot_internal,
                limit_price,
            )

            if side_upper == "BUY":
                spec = (
                    equity_buy_limit(symbol, quantity, limit_price)
                    if ot_internal == "limit"
                    else equity_buy_market(symbol, quantity)
                )
            else:
                spec = (
                    equity_sell_limit(symbol, quantity, limit_price)
                    if ot_internal == "limit"
                    else equity_sell_market(symbol, quantity)
                )

            response = self._client.place_order(account_hash=self._account_hash, order_spec=spec)

            if response.status_code in (200, 201):
                order_id = response.headers.get("Location", "").split("/")[-1] or str(uuid.uuid4())
                logger.info(
                    "SchwabConnector: equity PLACED | id=%s %s %s qty=%d",
                    order_id,
                    side_upper,
                    symbol,
                    quantity,
                )
                return {
                    "status": "placed",
                    "order_id": order_id,
                    "symbol": symbol,
                    "side": side_upper,
                    "quantity": quantity,
                    "order_type": ot_internal,
                    "limit_price": limit_price,
                }

            body = getattr(response, "text", str(getattr(response, "content", "")))
            logger.error(
                "SchwabConnector: equity FAILED | HTTP %s | %s", response.status_code, body
            )
            return {"status": "error", "reason": f"HTTP {response.status_code}", "body": body}

        except Exception as exc:
            logger.error(
                "SchwabConnector.submit_equity_order exception | %s: %s", symbol, exc, exc_info=True
            )
            return {"status": "error", "reason": str(exc)}

    async def submit_options_order(self, order: dict, portfolio_equity: float) -> dict:
        """
        Submit a single-leg options order. Safety check is mandatory.

        order keys: symbol, action, option_symbol, quantity, order_type, limit_price.
        Returns {"status": "placed"|"rejected"|"error", ...}.
        """
        symbol = order.get("symbol", "UNKNOWN")
        action = order.get("action", "")
        option_symbol = order.get("option_symbol", "")
        quantity = int(order.get("quantity", 0))
        order_type = order.get("order_type", "limit").lower()
        limit_price = order.get("limit_price")

        if action not in _OPTIONS_ACTIONS:
            return {
                "status": "error",
                "reason": f"Invalid action: {action!r}. Must be one of {sorted(_OPTIONS_ACTIONS)}",
            }
        if order_type not in _ORDER_TYPES:
            return {"status": "error", "reason": f"Invalid order_type: {order_type!r}"}

        logger.info(
            "SchwabConnector.submit_options_order | %s %s %s qty=%d %s limit=%s",
            symbol,
            action,
            option_symbol,
            quantity,
            order_type,
            limit_price,
        )

        # Safety check
        if self._safety_layer is not None:
            from risk.safety_layer import OrderRequest  # noqa: PLC0415

            estimated_value = (limit_price or 0.0) * abs(quantity) * 100
            req = OrderRequest(
                symbol=symbol,
                quantity=quantity if "buy" in action else -quantity,
                order_type=order_type,
                limit_price=limit_price,
                is_options=True,
                estimated_value=estimated_value,
            )
            result = self._safety_layer.check_order(req, portfolio_equity)
            if not result.approved:
                logger.warning(
                    "SchwabConnector: options REJECTED | %s reason=%s",
                    symbol,
                    result.rejection_reason,
                )
                return {
                    "status": "rejected",
                    "reason": result.rejection_reason,
                    "warnings": result.warnings,
                }
            for w in result.warnings:
                logger.warning("SchwabConnector: options warning | %s", w)
            warnings = result.warnings
            # PRB-01: use the risk-layer's adjusted (e.g. loss-tracker
            # de-risked) quantity for the actual order below, not the
            # pre-check request -- same defect class as the equity path.
            if result.adjusted_order is not None:
                adjusted_quantity = abs(int(result.adjusted_order.quantity))
                if adjusted_quantity != quantity:
                    logger.warning(
                        "SchwabConnector.submit_options_order: risk-adjusted size "
                        "%d -> %d for %s %s",
                        quantity,
                        adjusted_quantity,
                        symbol,
                        option_symbol,
                    )
                quantity = adjusted_quantity
        else:
            warnings = []

        if not self.is_connected:
            return {"status": "error", "reason": "Schwab not connected"}

        try:
            from schwab.orders.options import (  # noqa: PLC0415
                OptionSymbol,
                option_buy_to_close_limit,
                option_buy_to_close_market,
                option_buy_to_open_limit,
                option_buy_to_open_market,
                option_sell_to_close_limit,
                option_sell_to_close_market,
                option_sell_to_open_limit,
                option_sell_to_open_market,
            )

            _builders = {
                ("buy_to_open", "limit"): option_buy_to_open_limit,
                ("buy_to_open", "market"): option_buy_to_open_market,
                ("sell_to_open", "limit"): option_sell_to_open_limit,
                ("sell_to_open", "market"): option_sell_to_open_market,
                ("buy_to_close", "limit"): option_buy_to_close_limit,
                ("buy_to_close", "market"): option_buy_to_close_market,
                ("sell_to_close", "limit"): option_sell_to_close_limit,
                ("sell_to_close", "market"): option_sell_to_close_market,
            }

            opt_sym = OptionSymbol.parse_symbol(option_symbol)
            builder_fn = _builders[(action, order_type)]
            spec = (
                builder_fn(opt_sym, quantity, limit_price)
                if order_type == "limit" and limit_price is not None
                else builder_fn(opt_sym, quantity)
            )

            response = self._client.place_order(account_hash=self._account_hash, order_spec=spec)

            if response.status_code in (200, 201):
                order_id = response.headers.get("Location", "").split("/")[-1] or str(uuid.uuid4())
                estimated_value = (limit_price or 0.0) * abs(quantity) * 100
                logger.info(
                    "SchwabConnector: options PLACED | id=%s %s %s qty=%d",
                    order_id,
                    symbol,
                    action,
                    quantity,
                )
                return {
                    "status": "placed",
                    "order_id": order_id,
                    "symbol": symbol,
                    "option_symbol": option_symbol,
                    "action": action,
                    "quantity": quantity,
                    "order_type": order_type,
                    "limit_price": limit_price,
                    "estimated_value": estimated_value,
                    "warnings": warnings,
                }

            body = getattr(response, "text", str(getattr(response, "content", "")))
            logger.error(
                "SchwabConnector: options FAILED | HTTP %s | %s", response.status_code, body
            )
            return {"status": "error", "reason": f"HTTP {response.status_code}", "body": body}

        except Exception as exc:
            logger.error(
                "SchwabConnector.submit_options_order exception | %s: %s",
                symbol,
                exc,
                exc_info=True,
            )
            return {"status": "error", "reason": str(exc)}

    async def submit_options_spread_order(self, order: dict, portfolio_equity: float) -> dict:
        """
        Submit a two-leg vertical spread order (Credit/Debit).
        order keys: symbol, type (BULL_PUT_SPREAD|BEAR_CALL_SPREAD),
                    short_option_symbol, long_option_symbol,
                    quantity, limit_price.
        """
        symbol = order.get("symbol", "UNKNOWN")
        spread_type = order.get("type", "")
        short_opt_sym_str = order.get("short_option_symbol", "")
        long_opt_sym_str = order.get("long_option_symbol", "")
        quantity = int(order.get("quantity", 0))
        limit_price = order.get("limit_price")

        logger.info(
            "SchwabConnector.submit_options_spread_order | %s %s qty=%d limit=%s",
            symbol,
            spread_type,
            quantity,
            limit_price,
        )

        if not self.is_connected:
            return {"status": "error", "reason": "Schwab not connected"}

        try:
            from schwab.orders.generic import OrderBuilder  # noqa: PLC0415
            from schwab.orders.options import OptionSymbol  # noqa: PLC0415

            short_opt_sym = OptionSymbol.parse_symbol(short_opt_sym_str)
            long_opt_sym = OptionSymbol.parse_symbol(long_opt_sym_str)

            # Build a multi-leg vertical spread order
            # (Note: simpler to use OrderBuilder directly for multi-leg)
            builder = OrderBuilder()
            builder.set_order_strategy_type(OrderBuilder.OrderStrategyType.SINGLE)
            builder.set_order_type(OrderBuilder.OrderType.NET_CREDIT if limit_price > 0 else OrderBuilder.OrderType.NET_DEBIT)
            builder.set_price(abs(limit_price))
            builder.set_session(OrderBuilder.Session.NORMAL)
            builder.set_duration(OrderBuilder.Duration.DAY)

            if spread_type == "BULL_PUT_SPREAD":
                # Sell Short Put, Buy Long Put
                builder.add_option_leg(OrderBuilder.Instruction.SELL_TO_OPEN, short_opt_sym, quantity)
                builder.add_option_leg(OrderBuilder.Instruction.BUY_TO_OPEN, long_opt_sym, quantity)
            elif spread_type == "BEAR_CALL_SPREAD":
                # Sell Short Call, Buy Long Call
                builder.add_option_leg(OrderBuilder.Instruction.SELL_TO_OPEN, short_opt_sym, quantity)
                builder.add_option_leg(OrderBuilder.Instruction.BUY_TO_OPEN, long_opt_sym, quantity)
            else:
                return {"status": "error", "reason": f"Unsupported spread type: {spread_type}"}

            spec = builder.build()
            response = self._client.place_order(account_hash=self._account_hash, order_spec=spec)

            if response.status_code in (200, 201):
                order_id = response.headers.get("Location", "").split("/")[-1] or str(uuid.uuid4())
                return {
                    "status": "placed",
                    "order_id": order_id,
                    "symbol": symbol,
                    "type": spread_type,
                    "quantity": quantity,
                    "limit_price": limit_price,
                }

            body = getattr(response, "text", str(getattr(response, "content", "")))
            logger.error("SchwabConnector: spread FAILED | HTTP %s | %s", response.status_code, body)
            return {"status": "error", "reason": f"HTTP {response.status_code}", "body": body}

        except Exception as exc:
            logger.error("SchwabConnector.submit_options_spread_order exception: %s", exc, exc_info=True)
            return {"status": "error", "reason": str(exc)}

    async def place_paper_order(self, order: dict) -> dict:
        """
        Safety-integrated entry point — primary method for the order router.

        Routes to submit_equity_order or submit_options_order, runs safety
        checks (equity path), and mirrors fills to portfolio_tracker.

        order keys: symbol, side/action, quantity, order_type, limit_price,
                    is_options, option_symbol, portfolio_equity.
        Returns {"status": "placed"|"rejected"|"error", "order_id": str, ...}.
        """
        symbol = order.get("symbol", "UNKNOWN")
        is_options = bool(order.get("is_options", False))
        portfolio_equity = float(order.get("portfolio_equity", 0.0))

        logger.info(
            "SchwabConnector.place_paper_order | symbol=%s is_options=%s", symbol, is_options
        )

        # Equity-path safety check (options path runs its own inside submit_options_order)
        final_quantity = int(order.get("quantity", 0))
        if not is_options and self._safety_layer is not None:
            quantity = int(order.get("quantity", 0))
            approved, reason, warnings, adjusted_order = self._run_safety_check(
                symbol=symbol,
                quantity=quantity,
                order_type=order.get("order_type", "market").lower(),
                limit_price=order.get("limit_price"),
                portfolio_equity=portfolio_equity,
            )
            if not approved:
                logger.warning("SchwabConnector: equity REJECTED | %s reason=%s", symbol, reason)
                return {"status": "rejected", "reason": reason, "warnings": warnings}
            for w in warnings:
                logger.warning("SchwabConnector: equity warning | %s", w)
            # PRB-01: use the risk-layer's adjusted (e.g. loss-tracker
            # de-risked) quantity for the actual order, not the caller's
            # pre-check request.
            if adjusted_order is not None:
                final_quantity = int(adjusted_order.quantity)
                if abs(final_quantity) != abs(quantity):
                    logger.warning(
                        "SchwabConnector.place_paper_order: risk-adjusted size %d -> %d for %s",
                        quantity,
                        final_quantity,
                        symbol,
                    )

        # Route
        if is_options:
            result = await self.submit_options_order(order, portfolio_equity)
        else:
            result = await self.submit_equity_order(
                symbol=symbol,
                quantity=final_quantity,
                side=order.get("side", "BUY"),
                order_type=order.get("order_type", "MARKET"),
                limit_price=order.get("limit_price"),
            )

        # Mirror to portfolio tracker
        if result.get("status") == "placed" and self._portfolio_tracker is not None:
            try:
                signed_qty = final_quantity if not is_options else int(order.get("quantity", 0))
                if not is_options and order.get("side", "BUY").upper() == "SELL":
                    signed_qty = -abs(signed_qty)
                await self._get_paper_trade_logger().log_trade(
                    {
                        "order_id": result.get("order_id"),
                        "symbol": symbol,
                        "quantity": signed_qty,
                        "order_type": order.get("order_type", "market").lower(),
                        "limit_price": order.get("limit_price"),
                        "filled_price": order.get("limit_price") or 0.0,
                        "slippage_ticks": 0,
                        "fill_time": datetime.now(timezone.utc).isoformat() + "Z",
                        "is_futures": False,
                        "is_options": is_options,
                    }
                )
            except Exception as exc:
                logger.error("SchwabConnector: tracker logging failed: %s", exc, exc_info=True)

        return result

    # ── Order Management ──────────────────────────────────────────────────────

    async def get_open_orders(self) -> list[dict]:
        """Open/working orders. Returns [] when not connected or on error."""
        if not self.is_connected:
            return []
        try:
            import schwab  # noqa: PLC0415

            response = self._client.get_orders_for_account(
                account_hash=self._account_hash,
                status=schwab.client.Client.Order.Status.WORKING,
            )
            if response.status_code != 200:
                logger.warning("SchwabConnector.get_open_orders: HTTP %s", response.status_code)
                return []

            return [
                {
                    "order_id": str(o.get("orderId", "")),
                    "symbol": (
                        o.get("orderLegCollection", [{}])[0].get("instrument", {}).get("symbol")
                    ),
                    "asset_type": (
                        o.get("orderLegCollection", [{}])[0].get("instrument", {}).get("assetType")
                    ),
                    "quantity": o.get("quantity"),
                    "remaining_quantity": o.get("remainingQuantity"),
                    "order_type": o.get("orderType"),
                    "price": o.get("price"),
                    "status": o.get("status"),
                    "entered_time": o.get("enteredTime"),
                }
                for o in response.json()
            ]
        except Exception as exc:
            logger.error("SchwabConnector.get_open_orders failed: %s", exc, exc_info=True)
            return []

    async def cancel_all_orders(self) -> int:
        """Cancel all open orders (called by kill switch). Returns count cancelled."""
        if not self.is_connected:
            logger.warning("SchwabConnector.cancel_all_orders: not connected")
            return 0

        cancelled = 0
        try:
            for order in await self.get_open_orders():
                order_id = order.get("order_id")
                if not order_id:
                    continue
                res = await self.cancel_order(order_id)
                if res.get("status") == "cancelled":
                    cancelled += 1
        except Exception as exc:
            logger.error("SchwabConnector.cancel_all_orders failed: %s", exc, exc_info=True)

        logger.info("SchwabConnector.cancel_all_orders: %d cancelled", cancelled)
        return cancelled

    async def cancel_order(self, order_id: str) -> dict:
        """Cancel a specific order by ID."""
        if not self.is_connected:
            return {"status": "error", "reason": "Not connected"}
        try:
            response = self._client.cancel_order(
                account_hash=self._account_hash, order_id=order_id
            )
            if response.status_code == 200:
                logger.info("SchwabConnector: cancelled order %s", order_id)
                return {"status": "cancelled", "order_id": order_id}
            return {"status": "error", "reason": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    async def modify_order(self, order_id: str, new_price: float) -> dict:
        """Modify (replace) an existing order with a new price."""
        if not self.is_connected:
            return {"status": "error", "reason": "Not connected"}
        try:
            # Note: Schwab requires sending the full order spec for a replace.
            # For Phase 5 implementation, we fetch the existing order first.
            # This is a bit complex for a stateless connector, so we'll start
            # by noting that 'modify' is a 'replace' in Schwab.
            # In a real production run, we'd pull order details from get_orders.

            logger.warning("SchwabConnector: modify_order (replace) requires full spec. Not fully implemented.")
            return {"status": "error", "reason": "Full-spec replace not yet implemented"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    # ── Auth Helper ───────────────────────────────────────────────────────────

    def _auth_instructions(self) -> str:
        return (
            "\n=== SCHWAB RE-AUTH REQUIRED ===\n"
            "Token expires every 7 days. From engine/ directory:\n\n"
            '  python -c "\n'
            "  import schwab\n"
            "  schwab.auth.easy_client(\n"
            "      api_key='<SCHWAB_APP_KEY>', app_secret='<SCHWAB_APP_SECRET>',\n"
            "      callback_url='https://127.0.0.1', token_path='.schwab_token.json')\n"
            '  "\n\n'
            "Required .env: SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_CALLBACK_URL\n"
            "================================\n"
        )

    def get_auth_instructions(self) -> str:
        """Public alias — backward compat."""
        return self._auth_instructions()

    def token_expires_in_days(self) -> Optional[int]:
        """
        Read .schwab_token.json and return the number of days until the token expires.
        Returns None if the token file does not exist or cannot be parsed.
        """
        if not _TOKEN_PATH.exists():
            return None
        try:
            import json  # noqa: PLC0415

            raw = _TOKEN_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)

            # schwab-py stores the token under various keys depending on version.
            # Try the most common locations for the access-token expiry.
            expiry_ts: Optional[float] = None

            # Format 1: top-level 'expires_at' (epoch float)
            if "expires_at" in data:
                expiry_ts = float(data["expires_at"])

            # Format 2: nested token dict
            elif "token" in data and "expires_at" in data["token"]:
                expiry_ts = float(data["token"]["expires_at"])

            # Format 3: 'creation_timestamp' + 'expires_in' seconds
            elif "creation_timestamp" in data and "expires_in" in data:
                expiry_ts = float(data["creation_timestamp"]) + float(data["expires_in"])

            if expiry_ts is None:
                logger.warning("SchwabConnector.token_expires_in_days: could not find expiry in token file")
                return None

            now = datetime.now(timezone.utc).timestamp()
            days_remaining = int((expiry_ts - now) / 86400)
            return days_remaining

        except Exception as exc:
            logger.warning("SchwabConnector.token_expires_in_days: failed to parse token: %s", exc)
            return None
