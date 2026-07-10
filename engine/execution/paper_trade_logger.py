"""
PAPER TRADE LOGGER — Persistent JSON Logging for Paper Trading
===============================================================

Logs all paper trades to data/paper_trades.json for analysis,
backtest comparison, and audit trail.

Thread-safe file I/O with atomic writes to prevent corruption.

SCHEMA (data/paper_trades.json):
{
  "trades": [
    {
      "order_id": "uuid",
      "timestamp": "ISO 8601",
      "symbol": "MES",
      "side": "buy" | "sell",  # Inferred from quantity sign
      "quantity": 1,
      "order_type": "market" | "limit",
      "limit_price": null | 5300.00,
      "filled_price": 5300.10,
      "slippage_ticks": 0,
      "trade_value": 5300.10,
      "is_futures": true,
      "is_options": false,
      "pnl": null,  # Computed when position closed
    },
    ...
  ],
  "summary": {
    "total_trades": int,
    "total_win_trades": int,
    "total_loss_trades": int,
    "win_rate": float,
    "total_pnl": float,
    "largest_win": float,
    "largest_loss": float,
    "avg_trade_value": float,
  }
}
"""

import json
import logging
import warnings
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Optional, cast

logger = logging.getLogger(__name__)

__all__ = ["PaperTradeLogger"]


class PaperTradeLogger:
    """
    Thread-safe paper trade logger.

    Logs all simulated trades to a JSON file for later analysis.
    Optionally mirrors full flat→open→flat cycles onto ``PortfolioTracker`` (mode B).
    """

    def __init__(
        self,
        settings: Any,
        portfolio_tracker: Optional[Any] = None,
        *,
        mirror_to_tracker: bool = True,
        trades_file: Optional[Path] = None,
    ):
        """
        Args:
            settings: TradingConfig (retained for callers; paths are repo-relative).
            portfolio_tracker: Optional ``PortfolioTracker`` for API-aligned book (B).
            mirror_to_tracker: If False, only writes ``data/paper_trades.json``.
            trades_file: Override JSON path (tests); default ``data/paper_trades.json`` under repo.
        """
        warnings.warn(
            "PaperTradeLogger JSON path (data/paper_trades.json) is deprecated; "
            "SQLite (engine/data/jarvis_trader.db paper_trades table) is the source of truth. "
            "This logger is retained for historical audit only.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._settings = settings
        self._portfolio_tracker = portfolio_tracker
        self._mirror_to_tracker = bool(portfolio_tracker is not None and mirror_to_tracker)
        if trades_file is not None:
            self._trades_file = trades_file
            self._data_dir = trades_file.parent
        else:
            # paper_trade_logger.py lives at engine/execution/paper_trade_logger.py
            # parent       = engine/execution/
            # parent.parent = engine/          <-- correct root for data/
            self._data_dir = Path(__file__).parent.parent / "data"
            self._trades_file = self._data_dir / "paper_trades.json"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()  # Ensure atomic writes
        self._net_by_symbol: dict[str, float] = {}
        self._open_trade_id_by_symbol: dict[str, Optional[str]] = {}

        # Initialize file if it doesn't exist
        if not self._trades_file.exists():
            self._init_trades_file()

    def _init_trades_file(self) -> None:
        """Initialize empty trades file with schema."""
        with self._lock:
            try:
                self._trades_file.write_text(
                    json.dumps(
                        {
                            "trades": [],
                            "summary": {
                                "total_trades": 0,
                                "total_win_trades": 0,
                                "total_loss_trades": 0,
                                "win_rate": 0.0,
                                "total_pnl": 0.0,
                                "largest_win": 0.0,
                                "largest_loss": 0.0,
                                "avg_trade_value": 0.0,
                            },
                        },
                        indent=2,
                    )
                )
                logger.info("Initialized paper trades file: %s", self._trades_file)
            except Exception as exc:
                logger.error("Failed to initialize trades file: %s", exc, exc_info=True)

    async def log_trade(self, trade_data: dict) -> None:
        """
        Log a paper trade to the JSON file.

        Args:
            trade_data: Trade dict with:
              - order_id (UUID)
              - symbol
              - quantity (can be negative for sells)
              - order_type
              - limit_price (optional)
              - filled_price
              - slippage_ticks
              - fill_time (ISO 8601)
              - is_futures
              - is_options (optional)
        """
        try:
            # Infer side from quantity sign
            side = "buy" if trade_data.get("quantity", 0) > 0 else "sell"
            quantity = abs(trade_data.get("quantity", 0))
            filled_price = trade_data.get("filled_price", 0.0)
            trade_value = quantity * filled_price

            trade_record = {
                "order_id": trade_data.get("order_id"),
                "timestamp": trade_data.get("fill_time", datetime.utcnow().isoformat() + "Z"),
                "symbol": trade_data.get("symbol", "UNKNOWN"),
                "side": side,
                "quantity": quantity,
                "order_type": trade_data.get("order_type", "market"),
                "limit_price": trade_data.get("limit_price"),
                "filled_price": filled_price,
                "slippage_ticks": trade_data.get("slippage_ticks", 0),
                "trade_value": trade_value,
                "is_futures": trade_data.get("is_futures", False),
                "is_options": trade_data.get("is_options", False),
                "pnl": None,  # Computed when position closed
            }

            # Thread-safe file I/O
            with self._lock:
                # Read current data
                if self._trades_file.exists():
                    data = json.loads(self._trades_file.read_text())
                else:
                    data = {"trades": [], "summary": {}}

                # Append new trade
                data["trades"].append(trade_record)

                # Update summary
                self._update_summary(data)

                # Write atomically (write to temp, then rename)
                temp_file = self._trades_file.with_suffix(".tmp")
                temp_file.write_text(json.dumps(data, indent=2))
                temp_file.replace(self._trades_file)

            logger.debug(
                "PaperTradeLogger: Logged %s %d %s @ %.2f | order_id=%s",
                side.upper(),
                quantity,
                trade_record["symbol"],
                filled_price,
                trade_record["order_id"],
            )

            await self._maybe_mirror_to_tracker(
                symbol=str(trade_record["symbol"]),
                signed_qty=float(trade_data.get("quantity", 0)),
                filled_price=float(filled_price),
                order_id=str(trade_record["order_id"] or ""),
            )

        except Exception as exc:
            logger.error("Failed to log trade: %s", exc, exc_info=True)

    async def _maybe_mirror_to_tracker(
        self,
        symbol: str,
        signed_qty: float,
        filled_price: float,
        order_id: str,
    ) -> None:
        """Mirror full 0→position→0 nets onto PortfolioTracker; partials stay JSON-only."""
        if not self._mirror_to_tracker or self._portfolio_tracker is None:
            return

        sym = symbol.upper()
        prev = float(self._net_by_symbol.get(sym, 0.0))
        new = prev + signed_qty
        self._net_by_symbol[sym] = new
        notes = f"paper_trade_logger:{order_id}"

        try:
            if prev == 0.0 and new != 0.0:
                action = "buy" if signed_qty > 0 else "sell"
                # Forward-test attribution: if the live scanner is trading a
                # deployed registry candidate for this symbol, tag the trade with
                # its candidate_id so the forward-test loop can attribute it at
                # the precise (graduating) level. Fail-open and tag-only -- this
                # never changes whether/how the trade opens.
                candidate_id = None
                try:
                    from backtest.candidate_registry import live_candidate_for_symbol

                    candidate_id = live_candidate_for_symbol(sym)
                except Exception as _cid_err:  # pragma: no cover - defensive
                    logger.debug(
                        "PaperTradeLogger: candidate resolve failed for %s (non-fatal): %s",
                        sym,
                        _cid_err,
                    )
                # Decision-identity (P2): fingerprint of the running LLM decision
                # config that produced this trade, resolved to a per-symbol lineage.
                # config_hash is a property of the running config, so computing it
                # at open time == the config that just decided. Fail-open.
                decision_identity = None
                try:
                    from agents.decision_identity import current_decision_identity

                    decision_identity = current_decision_identity(sym)
                except Exception as _did_err:  # pragma: no cover - defensive
                    logger.debug(
                        "PaperTradeLogger: decision_identity failed for %s (non-fatal): %s",
                        sym,
                        _did_err,
                    )
                # #287 fix: this mirror path only ever sees the raw fill (symbol,
                # qty, price, order_id) -- no pipeline stop is in scope here, so
                # one is never invented from decision context. Instead synthesize
                # a defensive stop from the SAME dollar-risk budget that already
                # governs PaperStopMonitor's catastrophe cap, so the row is never
                # naked (stop_loss=NULL) between open and the monitor's next sweep.
                synthetic_stop = None
                try:
                    from services.paper_stop_monitor import synthesize_fallback_stop

                    synthetic_stop = synthesize_fallback_stop(
                        sym, action, filled_price, abs(signed_qty)
                    )
                except Exception as _stop_err:  # pragma: no cover - defensive
                    logger.debug(
                        "PaperTradeLogger: stop synthesis failed for %s (non-fatal): %s",
                        sym,
                        _stop_err,
                    )
                tid = self._portfolio_tracker.open_trade(
                    sym,
                    action,
                    abs(signed_qty),
                    filled_price,
                    notes=notes,
                    candidate_id=candidate_id,
                    decision_identity=decision_identity,
                    stop_loss=synthetic_stop,
                    stop_source="synthesized_fallback" if synthetic_stop is not None else None,
                )
                self._open_trade_id_by_symbol[sym] = tid
            elif prev != 0.0 and new == 0.0:
                tid = self._open_trade_id_by_symbol.get(sym)
                if tid:
                    try:
                        self._portfolio_tracker.close_trade(tid, filled_price)
                    except ValueError as exc:
                        # ExitPriceSanityError — a corrupt broker fill price.
                        # Fail-closed: skip the tracker mirror (the guard already
                        # logged CRITICAL) rather than crashing the fill loop.
                        logger.critical(
                            "PaperTradeLogger: exit-sanity rejected close mirror for %s @ %s: %s",
                            sym, filled_price, exc,
                        )
                self._open_trade_id_by_symbol[sym] = None
            elif prev != 0.0 and new != 0.0:
                logger.debug(
                    "PaperTradeLogger: tracker mirror skipped for %s (partial net prev=%s new=%s)",
                    sym,
                    prev,
                    new,
                )
        except Exception as exc:
            logger.error(
                "PaperTradeLogger: tracker mirror failed for %s: %s",
                sym,
                exc,
                exc_info=True,
            )

    def _update_summary(self, data: dict) -> None:
        """
        Recompute summary statistics from trades list.

        This is called after every trade to keep summary current.
        """
        trades = data.get("trades", [])

        if not trades:
            data["summary"] = {
                "total_trades": 0,
                "total_win_trades": 0,
                "total_loss_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "largest_win": 0.0,
                "largest_loss": 0.0,
                "avg_trade_value": 0.0,
            }
            return

        # Count trades with matching entry/exit pairs
        open_positions = {}  # symbol -> (quantity, entry_price)
        closed_pnls = []
        total_trade_value = 0.0

        for trade in trades:
            symbol = trade.get("symbol", "UNKNOWN")
            quantity = trade.get("quantity", 0)
            filled_price = trade.get("filled_price", 0.0)
            side = trade.get("side", "buy")
            trade_value = trade.get("trade_value", 0.0)

            total_trade_value += trade_value

            # Track position for P&L computation
            if symbol not in open_positions:
                open_positions[symbol] = (0, 0.0)

            current_qty, entry_price = open_positions[symbol]

            if side == "buy":
                new_qty = current_qty + quantity
                # Update entry price (weighted average)
                if new_qty > 0:
                    new_entry_price = (
                        current_qty * entry_price + quantity * filled_price
                    ) / new_qty
                else:
                    new_entry_price = entry_price
                open_positions[symbol] = (new_qty, new_entry_price)
            else:  # sell
                new_qty = current_qty - quantity
                if current_qty > 0:
                    # Closing position: compute P&L
                    pnl = quantity * (filled_price - entry_price)
                    closed_pnls.append(pnl)
                    trade["pnl"] = pnl  # Update the trade record
                open_positions[symbol] = (new_qty, entry_price)

        # Compute summary stats
        total_trades = len([t for t in trades if t.get("pnl") is not None])
        win_trades = len([p for p in closed_pnls if p > 0])
        loss_trades = len([p for p in closed_pnls if p < 0])
        total_pnl = sum(closed_pnls) if closed_pnls else 0.0
        largest_win = max(closed_pnls) if closed_pnls else 0.0
        largest_loss = min(closed_pnls) if closed_pnls else 0.0
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
        avg_trade_value = total_trade_value / len(trades) if trades else 0.0

        data["summary"] = {
            "total_trades": total_trades,
            "total_win_trades": win_trades,
            "total_loss_trades": loss_trades,
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 2),
            "largest_win": round(largest_win, 2),
            "largest_loss": round(largest_loss, 2),
            "avg_trade_value": round(avg_trade_value, 2),
        }

    # ── Query Methods ──────────────────────────────────────────────────────────

    async def get_all_trades(self) -> list[dict[str, Any]]:
        """
        Get all trades ever logged.

        Returns:
            List of trade dicts
        """
        with self._lock:
            try:
                if self._trades_file.exists():
                    data = json.loads(self._trades_file.read_text())
                    return cast(list[dict[str, Any]], data.get("trades", []))
            except Exception as exc:
                logger.error("Failed to read trades file: %s", exc, exc_info=True)
        return []

    async def get_trades_today(self) -> list[dict]:
        """
        Get trades logged today (UTC).

        Returns:
            List of trade dicts from today
        """
        today = datetime.utcnow().date()
        all_trades = await self.get_all_trades()
        today_trades = []

        for trade in all_trades:
            timestamp_str = trade.get("timestamp", "")
            try:
                trade_date = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).date()
                if trade_date == today:
                    today_trades.append(trade)
            except (ValueError, AttributeError):
                pass

        return today_trades

    async def get_trade_by_id(self, order_id: str) -> Optional[dict]:
        """
        Get a specific trade by order ID.

        Args:
            order_id: Order UUID to look up

        Returns:
            Trade dict if found, None otherwise
        """
        all_trades = await self.get_all_trades()
        for trade in all_trades:
            if trade.get("order_id") == order_id:
                return trade
        return None

    async def get_paper_trading_summary(self) -> dict:
        """
        Get paper trading summary statistics.

        Returns:
            {
                "total_trades": int,
                "win_rate": float,
                "total_pnl": float,
                "largest_win": float,
                "largest_loss": float,
                "avg_trade_value": float,
                "trades_today": int,
                "symbols_traded": list[str],
            }
        """
        with self._lock:
            try:
                if self._trades_file.exists():
                    data = json.loads(self._trades_file.read_text())
                    summary = data.get("summary", {})

                    # Add trades_today and symbols_traded
                    today_trades = await self.get_trades_today()
                    all_trades = data.get("trades", [])
                    symbols = {t.get("symbol") for t in all_trades if t.get("symbol")}

                    return {
                        **summary,
                        "trades_today": len(today_trades),
                        "symbols_traded": sorted(symbols),
                        "last_updated": datetime.utcnow().isoformat() + "Z",
                    }
            except Exception as exc:
                logger.error("Failed to get summary: %s", exc, exc_info=True)

        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "error": "Could not read trades file",
        }

    async def export_trades_csv(self, output_path: Path) -> bool:
        """
        Export paper trades to CSV for analysis in Excel/Python.

        Args:
            output_path: Path to write CSV file

        Returns:
            True if successful
        """
        try:
            trades = await self.get_all_trades()
            if not trades:
                logger.warning("No trades to export")
                return False

            # Write CSV header
            csv_lines = [
                "order_id,timestamp,symbol,side,quantity,order_type,"
                "limit_price,filled_price,slippage_ticks,trade_value,is_futures,is_options,pnl"
            ]

            # Write trades
            for trade in trades:
                csv_lines.append(
                    f"{trade.get('order_id')},"
                    f"{trade.get('timestamp')},"
                    f"{trade.get('symbol')},"
                    f"{trade.get('side')},"
                    f"{trade.get('quantity')},"
                    f"{trade.get('order_type')},"
                    f"{trade.get('limit_price') or ''},"
                    f"{trade.get('filled_price')},"
                    f"{trade.get('slippage_ticks')},"
                    f"{trade.get('trade_value')},"
                    f"{trade.get('is_futures')},"
                    f"{trade.get('is_options')},"
                    f"{trade.get('pnl') or ''}"
                )

            output_path.write_text("\n".join(csv_lines))
            logger.info("Exported %d trades to %s", len(trades), output_path)
            return True

        except Exception as exc:
            logger.error("Failed to export trades: %s", exc, exc_info=True)
            return False
