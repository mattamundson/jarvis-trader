"""
SCHWAB CONNECTOR — STATUS: INCOMPLETE (March 2026)
===================================================

NOT WIRED TO ORDER ROUTER. OAuth flow partially implemented.
Do NOT route orders through this module until completion and testing.

This connector is 60% complete. It provides:
  - OAuth token management (partial)
  - Account summary queries (working)
  - Quote fetching for equities/options (working)
  - Options chain retrieval (working)
  - Single-leg options order submission (implemented but untested)
  - Order cancellation (implemented but untested)

MISSING / TODO:
  - [ ] Full OAuth2 flow integration with dashboard
  - [ ] Automated token refresh (currently manual every 7 days)
  - [ ] Integration with order router dispatch
  - [ ] Testing against live Schwab sandbox
  - [ ] Error handling refinements
  - [ ] Logging and observability improvements

Until completion, all equity/options orders must route through
alternative connectors (e.g., IB Gateway for stocks, manual for options).

NOTE: Schwab API can stream futures QUOTES but CANNOT execute futures ORDERS.
      Use IBKRExecutor for all futures order execution.

For re-auth when token expires (every 7 days):
  python -c "import schwab; schwab.auth.easy_client(...)"
  Token stored at: engine/.schwab_token.json
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Guard: mark this module as incomplete
SCHWAB_READY = False


def check_schwab_ready():
    """Prevent accidental use of incomplete Schwab connector."""
    if not SCHWAB_READY:
        raise RuntimeError(
            "Schwab connector is incomplete (March 2026). "
            "Do NOT use in production. Set SCHWAB_READY=True only after "
            "finishing implementation, testing, and reviewing TODO items above."
        )


# Token file lives in the engine/ directory (one level above this file)
_TOKEN_PATH = Path(__file__).parent.parent / ".schwab_token.json"

__all__ = ["SchwabConnector"]


class SchwabConnector:
    """
    Thin wrapper around the schwab-py library for equity and options execution.

    Only single-leg options orders are supported by design — defined-risk always.
    Spreads and naked shorts are NOT implemented.
    """

    def __init__(self, settings, safety_layer):
        self._settings = settings
        self._safety_layer = safety_layer
        self._client = None  # schwab.AsyncClient set in initialize()
        self._connected = False
        self._account_hash: Optional[str] = None  # Schwab uses hashed account IDs

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> bool:
        """
        Initialize Schwab client using schwab-py library.
        Uses token file at .schwab_token.json (created during auth flow).
        Returns True if connected.
        """
        check_schwab_ready()

        api_key = self._settings.SCHWAB_APP_KEY
        app_secret = self._settings.SCHWAB_APP_SECRET
        callback_url = self._settings.SCHWAB_CALLBACK_URL

        if not api_key or not app_secret:
            logger.error(
                "Schwab credentials missing — set SCHWAB_APP_KEY and SCHWAB_APP_SECRET in .env\n%s",
                self.get_auth_instructions(),
            )
            self._connected = False
            return False

        if not _TOKEN_PATH.exists():
            logger.error(
                "Schwab token file not found at %s\n%s",
                _TOKEN_PATH,
                self.get_auth_instructions(),
            )
            self._connected = False
            return False

        try:
            import schwab  # noqa: PLC0415  (lazy import — optional dependency)

            self._client = schwab.auth.easy_client(
                api_key=api_key,
                app_secret=app_secret,
                callback_url=callback_url,
                token_path=str(_TOKEN_PATH),
            )

            # Resolve the first account hash for subsequent API calls
            response = self._client.get_account_numbers()
            if response.status_code == 200:
                accounts = response.json()
                if accounts:
                    self._account_hash = accounts[0]["hashValue"]
                    logger.info(
                        "Schwab connected — account hash: %s…",
                        self._account_hash[:8] if self._account_hash else "n/a",
                    )
            else:
                logger.warning(
                    "Schwab: get_account_numbers returned %s — partial init",
                    response.status_code,
                )

            self._connected = True
            return True

        except Exception as exc:
            logger.error("Schwab initialization failed: %s", exc, exc_info=True)
            self._connected = False
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_account_summary(self) -> dict:
        """Account balances and positions from Schwab."""
        check_schwab_ready()

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
            account = data.get("securitiesAccount", {})
            balances = account.get("currentBalances", {})
            positions_raw = account.get("positions", [])

            positions = []
            for pos in positions_raw:
                instrument = pos.get("instrument", {})
                positions.append(
                    {
                        "symbol": instrument.get("symbol"),
                        "asset_type": instrument.get("assetType"),
                        "quantity": pos.get("longQuantity", 0) - pos.get("shortQuantity", 0),
                        "average_price": pos.get("averagePrice"),
                        "market_value": pos.get("marketValue"),
                        "unrealized_pnl": pos.get("currentDayProfitLoss"),
                    }
                )

            return {
                "account_hash": self._account_hash,
                "equity": balances.get("equity"),
                "cash_balance": balances.get("cashBalance"),
                "buying_power": balances.get("buyingPower"),
                "day_trading_buying_power": balances.get("dayTradingBuyingPower"),
                "positions": positions,
            }

        except Exception as exc:
            logger.error("get_account_summary failed: %s", exc, exc_info=True)
            return {"error": str(exc)}

    # ── Market Data ───────────────────────────────────────────────────────────

    async def get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Get real-time quotes for equity/ETF/options symbols."""
        check_schwab_ready()

        if not self.is_connected:
            return {}

        try:
            response = self._client.get_quotes(symbols)
            if response.status_code != 200:
                logger.warning("get_quotes HTTP %s for %s", response.status_code, symbols)
                return {}

            raw = response.json()
            quotes: dict[str, dict] = {}
            for symbol, data in raw.items():
                quote = data.get("quote", {})
                quotes[symbol] = {
                    "symbol": symbol,
                    "bid": quote.get("bidPrice"),
                    "ask": quote.get("askPrice"),
                    "last": quote.get("lastPrice"),
                    "volume": quote.get("totalVolume"),
                    "mark": quote.get("mark"),
                    "change_pct": quote.get("netPercentChangeInDouble"),
                }
            return quotes

        except Exception as exc:
            logger.error("get_quotes failed: %s", exc, exc_info=True)
            return {}

    async def get_options_chain(
        self,
        symbol: str,
        expiry_date: str | None = None,
    ) -> dict:
        """
        Get options chain for a symbol.
        Returns calls and puts with strikes, premiums, Greeks.

        expiry_date format: "YYYY-MM-DD"  (None = nearest expiry)
        """
        check_schwab_ready()

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
                # schwab-py accepts from_date / to_date as datetime.date objects
                from datetime import date as _date  # noqa: PLC0415

                parsed = _date.fromisoformat(expiry_date)
                kwargs["from_date"] = parsed
                kwargs["to_date"] = parsed

            response = self._client.get_option_chain(**kwargs)
            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}"}

            data = response.json()
            underlying = data.get("underlying", {})

            def _parse_leg(exp_map: dict) -> list[dict]:
                legs = []
                for exp_str, strikes in exp_map.items():
                    for strike_str, contracts in strikes.items():
                        for contract in contracts:
                            legs.append(
                                {
                                    "option_symbol": contract.get("symbol"),
                                    "expiry": exp_str,
                                    "strike": float(strike_str),
                                    "bid": contract.get("bid"),
                                    "ask": contract.get("ask"),
                                    "last": contract.get("last"),
                                    "volume": contract.get("totalVolume"),
                                    "open_interest": contract.get("openInterest"),
                                    "delta": contract.get("delta"),
                                    "gamma": contract.get("gamma"),
                                    "theta": contract.get("theta"),
                                    "vega": contract.get("vega"),
                                    "iv": contract.get("volatility"),
                                    "in_the_money": contract.get("inTheMoney"),
                                }
                            )
                return legs

            return {
                "symbol": symbol,
                "underlying_price": underlying.get("mark"),
                "calls": _parse_leg(data.get("callExpDateMap", {})),
                "puts": _parse_leg(data.get("putExpDateMap", {})),
            }

        except Exception as exc:
            logger.error("get_options_chain failed for %s: %s", symbol, exc, exc_info=True)
            return {"error": str(exc)}

    # ── Order Execution ───────────────────────────────────────────────────────

    async def submit_options_order(
        self,
        order: dict,
        portfolio_equity: float,
    ) -> dict:
        """
        Submit a single-leg options order (buy/sell to open/close).

        CRITICAL: Runs safety_layer.check_order() first — order is rejected if
        any risk check fails.

        order dict format:
          symbol:        str   — underlying (e.g. "SPY")
          action:        str   — "buy_to_open" | "sell_to_open" |
                                 "buy_to_close" | "sell_to_close"
          option_symbol: str   — OCC format (e.g. "SPY   260117C00580000")
          quantity:      int   — number of contracts
          order_type:    str   — "market" | "limit"
          limit_price:   float | None

        Only single-leg orders are supported by design (defined-risk always).
        Spreads and naked shorts are NOT implemented.

        TODO: Remove check_schwab_ready() guard once implementation is complete and tested.
        """
        check_schwab_ready()

        symbol = order.get("symbol", "UNKNOWN")
        action = order.get("action", "")
        option_symbol = order.get("option_symbol", "")
        quantity = int(order.get("quantity", 0))
        order_type = order.get("order_type", "limit")
        limit_price = order.get("limit_price")

        logger.info(
            "Schwab order attempt | symbol=%s action=%s option=%s qty=%d type=%s limit=%s equity=$%.0f",
            symbol,
            action,
            option_symbol,
            quantity,
            order_type,
            limit_price,
            portfolio_equity,
        )

        # ── Safety check (mandatory — ALWAYS before broker call) ──────────────
        from risk.safety_layer import OrderRequest  # noqa: PLC0415

        # Estimate order value: limit_price * quantity * 100 (options multiplier)
        estimated_value = (limit_price or 0.0) * abs(quantity) * 100

        order_req = OrderRequest(
            symbol=symbol,
            quantity=quantity if "buy" in action else -quantity,
            order_type=order_type,
            limit_price=limit_price,
            is_options=True,
            estimated_value=estimated_value,
        )

        risk_result = self._safety_layer.check_order(order_req, portfolio_equity)
        if not risk_result.approved:
            logger.warning(
                "Schwab order REJECTED by safety layer | symbol=%s reason=%s",
                symbol,
                risk_result.rejection_reason,
            )
            return {
                "status": "rejected",
                "reason": risk_result.rejection_reason,
                "warnings": risk_result.warnings,
            }

        if risk_result.warnings:
            for w in risk_result.warnings:
                logger.warning("Schwab order warning | %s", w)

        if not self.is_connected:
            return {"status": "error", "reason": "Schwab not connected"}

        # ── Map action to schwab-py instruction ───────────────────────────────
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

            builder_fn = _builders.get((action, order_type))
            if builder_fn is None:
                return {
                    "status": "error",
                    "reason": f"Unsupported action/order_type combination: {action}/{order_type}",
                }

            opt_sym = OptionSymbol.parse_symbol(option_symbol)

            if order_type == "limit" and limit_price is not None:
                order_spec = builder_fn(opt_sym, quantity, limit_price)
            else:
                order_spec = builder_fn(opt_sym, quantity)

            response = self._client.place_order(
                account_hash=self._account_hash,
                order_spec=order_spec,
            )

            if response.status_code in (200, 201):
                order_id = response.headers.get("Location", "").split("/")[-1]
                logger.info(
                    "Schwab order PLACED | symbol=%s action=%s qty=%d order_id=%s",
                    symbol,
                    action,
                    quantity,
                    order_id,
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
                    "warnings": risk_result.warnings,
                }
            else:
                error_body = response.text if hasattr(response, "text") else str(response.content)
                logger.error(
                    "Schwab order FAILED | HTTP %s | body=%s", response.status_code, error_body
                )
                return {
                    "status": "error",
                    "reason": f"HTTP {response.status_code}",
                    "body": error_body,
                }

        except Exception as exc:
            logger.error(
                "submit_options_order exception | symbol=%s: %s", symbol, exc, exc_info=True
            )
            return {"status": "error", "reason": str(exc)}

    # ── Order Management ─────────────────────────────────────────────────────

    async def cancel_all_orders(self) -> int:
        """Cancel all open Schwab orders. Called by kill switch."""
        check_schwab_ready()

        if not self.is_connected:
            logger.warning("cancel_all_orders: Schwab not connected")
            return 0

        cancelled = 0
        try:
            open_orders = await self.get_open_orders()
            for order in open_orders:
                order_id = order.get("order_id")
                if not order_id:
                    continue
                try:
                    response = self._client.cancel_order(
                        account_hash=self._account_hash,
                        order_id=order_id,
                    )
                    if response.status_code == 200:
                        cancelled += 1
                        logger.info("Schwab order cancelled: %s", order_id)
                    else:
                        logger.warning(
                            "Failed to cancel order %s — HTTP %s",
                            order_id,
                            response.status_code,
                        )
                except Exception as exc:
                    logger.error("Error cancelling order %s: %s", order_id, exc)

        except Exception as exc:
            logger.error("cancel_all_orders failed: %s", exc, exc_info=True)

        logger.info("Schwab cancel_all_orders: %d cancelled", cancelled)
        return cancelled

    async def get_open_orders(self) -> list[dict]:
        """List all open orders."""
        check_schwab_ready()

        if not self.is_connected:
            return []

        try:
            import schwab  # noqa: PLC0415

            response = self._client.get_orders_for_account(
                account_hash=self._account_hash,
                status=schwab.client.Client.Order.Status.WORKING,
            )
            if response.status_code != 200:
                logger.warning("get_open_orders HTTP %s", response.status_code)
                return []

            raw = response.json()
            orders = []
            for o in raw:
                legs = o.get("orderLegCollection", [{}])
                first_leg = legs[0] if legs else {}
                instrument = first_leg.get("instrument", {})
                orders.append(
                    {
                        "order_id": str(o.get("orderId", "")),
                        "symbol": instrument.get("symbol"),
                        "asset_type": instrument.get("assetType"),
                        "quantity": o.get("quantity"),
                        "remaining_quantity": o.get("remainingQuantity"),
                        "order_type": o.get("orderType"),
                        "price": o.get("price"),
                        "status": o.get("status"),
                        "entered_time": o.get("enteredTime"),
                    }
                )
            return orders

        except Exception as exc:
            logger.error("get_open_orders failed: %s", exc, exc_info=True)
            return []

    # ── Auth Helper ───────────────────────────────────────────────────────────

    def get_auth_instructions(self) -> str:
        """Return instructions for re-authenticating when token expires."""
        return (
            "\n"
            "=== SCHWAB RE-AUTH REQUIRED ===\n"
            "The Schwab refresh token expires every 7 days.\n"
            "\n"
            "To re-authenticate, run the following from the engine/ directory:\n"
            "\n"
            '  python -c "\n'
            "  import schwab\n"
            "  schwab.auth.easy_client(\n"
            "      api_key='<SCHWAB_APP_KEY>',\n"
            "      app_secret='<SCHWAB_APP_SECRET>',\n"
            "      callback_url='https://127.0.0.1',\n"
            "      token_path='.schwab_token.json',\n"
            "  )\n"
            '  "\n'
            "\n"
            "A browser window will open. Log in to Schwab and approve the app.\n"
            "The token will be saved to engine/.schwab_token.json automatically.\n"
            "\n"
            "Environment variables required in .env:\n"
            "  SCHWAB_APP_KEY=<your_app_key>\n"
            "  SCHWAB_APP_SECRET=<your_app_secret>\n"
            "  SCHWAB_CALLBACK_URL=https://127.0.0.1  (must match your app settings)\n"
            "================================\n"
        )
