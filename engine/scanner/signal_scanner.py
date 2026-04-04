"""
Scheduled Signal Scanner for JARVIS TRADER
============================================
Automatically scans validated instruments on a schedule during futures market hours.

Market hours (US Futures):
  Sunday 5:00 PM - Friday 4:00 PM CT
  (CME E-mini S&P 500 and other contracts)

Scanner behavior:
  - Runs every 60 minutes during market hours
  - Scans MCL (crude oil) and MNQ (micro Nasdaq) by default
  - Calls the trading pipeline for each symbol
  - Creates pending approvals when signals fire
  - Logs all results for audit trail
  - Can be paused/resumed via API

Status tracking:
  - Active / Paused state persisted in memory
  - Last scan timestamp
  - Next scheduled scan
  - Error tracking for failed scans
"""

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis_trader.scanner")


def _is_futures_market_hours() -> bool:
    """
    Check if current time is during US futures market hours.
    Returns True if Sun 5pm - Fri 4pm CT.
    """
    now = datetime.now(timezone.utc)
    ct_offset = timedelta(hours=-6)  # Central Time offset from UTC
    now_ct = now + ct_offset

    weekday = now_ct.weekday()  # 0=Monday, 6=Sunday
    current_time = now_ct.time()

    sunday_open = time(17, 0)  # 5pm CT Sunday
    friday_close = time(16, 0)  # 4pm CT Friday

    if weekday == 6:  # Sunday
        return current_time >= sunday_open
    elif weekday < 5:  # Monday-Friday
        return current_time < friday_close
    elif weekday == 5:  # Saturday
        return False
    return False


class SignalScanner:
    """
    Background signal scanner for automated market surveillance.
    Runs on a configurable schedule during market hours.
    """

    def __init__(
        self,
        trading_pipeline,
        db_manager,
        symbols: Optional[List[str]] = None,
        scan_interval_minutes: int = 60,
    ):
        """
        Args:
            trading_pipeline: TradingPipeline instance (from main.py)
            db_manager: DatabaseManager instance for creating approvals
            symbols: List of symbols to scan (default: ["MCL", "MNQ"])
            scan_interval_minutes: How often to scan (default: 60)
        """
        self.trading_pipeline = trading_pipeline
        self.db_manager = db_manager
        self.symbols = symbols or ["MCL", "MNQ"]
        self.scan_interval_minutes = scan_interval_minutes
        self._paper_tracker = None  # injected post-construction via set_paper_tracker()

        self._active = False
        self._last_scan_at: Optional[datetime] = None
        self._next_scan_at: Optional[datetime] = None
        self._task: Optional[asyncio.Task[Any]] = None
        self._error_count = 0
        self._total_scans = 0
        self._approval_count = 0

    def set_paper_tracker(self, tracker) -> None:
        """Inject paper tracker for breakeven stop management."""
        self._paper_tracker = tracker

    async def start(self) -> None:
        """Start the background scanner task."""
        if self._active:
            logger.warning("[Scanner] Already active")
            return

        self._active = True
        logger.info(
            f"[Scanner] Starting on symbols {self.symbols} "
            f"(every {self.scan_interval_minutes} min)"
        )
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the scanner gracefully."""
        if not self._active:
            logger.warning("[Scanner] Already stopped")
            return

        self._active = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Scanner] Stopped")

    async def pause(self) -> None:
        """Pause scanning (keeps task alive, skips logic)."""
        if not self._active:
            logger.warning("[Scanner] Not active")
            return
        self._active = False
        logger.info("[Scanner] Paused")

    async def resume(self) -> None:
        """Resume from pause."""
        if self._active:
            logger.warning("[Scanner] Already active")
            return
        self._active = True
        logger.info("[Scanner] Resumed")

    def status(self) -> Dict[str, Any]:
        """Return current scanner state."""
        return {
            "active": self._active,
            "symbols": self.symbols,
            "scan_interval_minutes": self.scan_interval_minutes,
            "last_scan_at": self._last_scan_at.isoformat() if self._last_scan_at else None,
            "next_scan_at": self._next_scan_at.isoformat() if self._next_scan_at else None,
            "total_scans": self._total_scans,
            "approvals_created": self._approval_count,
            "errors": self._error_count,
        }

    async def _run(self) -> None:
        """Background loop — runs until stop() is called."""
        logger.info("[Scanner] Background loop started")

        while True:
            try:
                now = datetime.now(timezone.utc)
                self._next_scan_at = now + timedelta(minutes=self.scan_interval_minutes)

                # Only scan if market is open
                if not _is_futures_market_hours():
                    logger.debug("[Scanner] Outside market hours, skipping scan")
                    await asyncio.sleep(60)
                    continue

                if not self._active:
                    logger.debug("[Scanner] Paused, skipping scan")
                    await asyncio.sleep(60)
                    continue

                await self._run_scan()

                # Sleep until next interval
                await asyncio.sleep(self.scan_interval_minutes * 60)

            except asyncio.CancelledError:
                logger.info("[Scanner] Task cancelled")
                break
            except Exception as e:
                logger.error(f"[Scanner] Unexpected error in loop: {e}", exc_info=True)
                self._error_count += 1
                await asyncio.sleep(60)  # Wait before retry

    async def _run_scan(self) -> None:
        """Execute one complete scan of all symbols."""
        self._last_scan_at = datetime.now(timezone.utc)
        self._total_scans += 1
        logger.info(f"[Scanner] Starting scan #{self._total_scans}")

        # Check breakeven stops for all open positions before scanning for new signals
        if self._paper_tracker is not None and hasattr(
            self._paper_tracker, "check_and_move_breakeven"
        ):
            for trade_id, trade in list(self._paper_tracker._open.items()):
                if not trade.is_open:
                    continue
                try:
                    self._paper_tracker.check_and_move_breakeven(trade_id, trade.entry_price)
                except Exception as exc:
                    logger.debug("[Scanner] breakeven check failed for %s: %s", trade_id[:8], exc)

        for symbol in self.symbols:
            try:
                await self._scan_symbol(symbol)
            except Exception as e:
                logger.error(f"[Scanner] Failed to scan {symbol}: {e}", exc_info=True)
                self._error_count += 1

        logger.info(f"[Scanner] Scan #{self._total_scans} complete")

    async def _scan_symbol(self, symbol: str) -> None:
        """
        Run the pipeline for one symbol, create approval if signal fired.
        """
        if not self.trading_pipeline:
            logger.warning("[Scanner] Pipeline not available, skipping scan")
            return

        if not self.db_manager:
            logger.warning("[Scanner] DB manager not available, skipping scan")
            return

        # Session timing: no entries in first 5 min of RTH (9:30-9:35 ET) or last 15 min (3:45-4:00 ET)
        now_et = datetime.now(timezone.utc) + timedelta(hours=-5)  # ET offset (approximate)
        current_time_et = now_et.time()
        rth_open = time(9, 30)
        rth_no_entry_start = time(9, 35)  # Can enter after 9:35
        rth_no_entry_end = time(15, 45)  # Must stop at 3:45 PM ET
        rth_close = time(16, 0)

        in_banned_window = (
            (current_time_et >= rth_open and current_time_et < rth_no_entry_start)  # First 5 min
            or (current_time_et >= rth_no_entry_end and current_time_et <= rth_close)  # Last 15 min
        )
        if in_banned_window:
            logger.debug(
                f"[Scanner] {symbol}: skipping — in banned session timing window ({current_time_et})"
            )
            return

        # MCL EIA inventory report blackout: Wednesday 10:15-11:00 ET
        if symbol == "MCL" and now_et.weekday() == 2:  # Wednesday
            blackout_start = time(10, 15)
            blackout_end = time(11, 0)
            if blackout_start <= current_time_et <= blackout_end:
                logger.debug(
                    "[Scanner] MCL: skipping — EIA inventory blackout (%s)", current_time_et
                )
                return

        logger.debug(f"[Scanner] Analyzing {symbol}")

        try:
            result = await self.trading_pipeline.analyze_and_decide(
                symbol=symbol,
                is_futures=True,
                timeframe="1h",
            )

            if not result:
                logger.warning(f"[Scanner] No result for {symbol}")
                return

            final_action = result.get("final_action", "hold")
            if final_action not in ("buy", "sell"):
                logger.debug(f"[Scanner] {symbol} signal: {final_action}, no action needed")
                return

            # Signal fired! Create pending approval
            quantity = result.get("final_quantity", 1)
            entry_price = result.get("trade_decision", {}).get("entry_price", None)
            snapshot = result

            approval_id = self.db_manager.insert_pending_approval(
                symbol=symbol,
                action=final_action,
                quantity=quantity,
                entry_price=entry_price,
                pipeline_snapshot=snapshot,
            )

            self._approval_count += 1
            logger.info(
                f"[Scanner] {symbol} signal: {final_action} {quantity} "
                f"(approval_id={approval_id[:8]})"
            )

            from notifications.pending_approval_notify import (
                notify_pending_approval_queued,
            )

            await notify_pending_approval_queued(
                approval_id=approval_id,
                symbol=symbol,
                action=final_action,
                quantity=float(quantity) if quantity is not None else None,
                entry_price=float(entry_price) if entry_price is not None else None,
            )

            # OpenClaw WhatsApp alert for non-HOLD signals
            try:
                from notifications.openclaw_notifier import notify_signal as _oc_signal

                await _oc_signal(
                    symbol=symbol,
                    action=final_action,
                    confidence=float(result.get("confidence", 0.0)),
                    reason=str(result.get("reason", "")),
                    market="futures",
                )
            except Exception as _oc_err:
                logger.debug(f"OpenClaw signal notification skipped: {_oc_err}")

        except Exception as e:
            logger.error(f"[Scanner] Pipeline error for {symbol}: {e}", exc_info=True)
            self._error_count += 1
