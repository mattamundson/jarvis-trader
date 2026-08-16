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
import os
import time as _time_module
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from utils.data_provenance import build_data_provenance, stamp_signal_data

logger = logging.getLogger("jarvis_trader.scanner")


def _is_futures_market_hours() -> bool:
    """
    Check if current time is during US futures market hours.
    Returns True if Sun 5pm - Fri 4pm CT (DST-aware).

    CME Globex schedule (America/Chicago):
      - Sunday 5:00 PM → Friday 4:00 PM CT (continuous)
      - Daily maintenance break: 4:00 PM – 5:00 PM CT (Mon-Thu)
      - Closed: Friday 4:00 PM → Sunday 5:00 PM
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

    ct = ZoneInfo("America/Chicago")
    now_ct = datetime.now(ct)
    weekday = now_ct.weekday()  # 0=Monday, 6=Sunday
    h = now_ct.hour

    # Saturday: fully closed
    if weekday == 5:
        return False
    # Sunday: open at 5:00 PM CT
    if weekday == 6:
        return h >= 17
    # Friday: closed at 4:00 PM CT
    if weekday == 4:
        return h < 16
    # Monday–Thursday: open except 4:00–5:00 PM CT maintenance break
    return not (h == 16)


def _is_equity_market_hours() -> bool:
    """True during US equity Regular Trading Hours (9:30 AM–4:00 PM ET, Mon–Fri).

    The scan loop gates only on *futures* hours (≈23h/day), so without this an
    equity symbol (SPY/QQQ/AAPL) can be auto-submitted long after the cash
    market closed — the 20:24 off-hours stale-price fill class. DST-aware.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:  # Sat/Sun
        return False
    return time(9, 30) <= now_et.time() < time(16, 0)


def _market_hours_submission_guard_enabled() -> bool:
    """Opt-out flag for the equity market-hours submission guard. Default ON."""
    return os.getenv("ENABLE_MARKET_HOURS_SUBMISSION_GUARD", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def _symbol_is_halted_for_scanner(symbol: str) -> bool:
    """Fail-safe halt check for the scanner's paper-mode bypass (GT-52).

    The bypass below writes straight to paper_trades without ever consulting
    an authorization gate. This is deliberately narrower than full gate-v2
    authorization (`gate_v2_policy.is_strategy_authorized`): it only blocks
    symbols the repo has explicitly halted -- membership in
    DO_NOT_TRADE_SYMBOLS, or a PAPER_CONFIGS entry disabled via
    enabled=False. Symbols with no PAPER_CONFIGS entry at all (the equities
    scanner population: SPY/QQQ/AAPL/TSLA) are deliberately NOT touched by
    this check -- see the 2026-08-03 Amo decision recorded in
    engine/CLAUDE.md "Active Instruments > Equities" to keep them trading
    as-is pending a separate, explicit policy call on that broader gap.
    """
    try:
        from engine.backtest.paper_config import PAPER_CONFIGS
        from engine.backtest.signals import DO_NOT_TRADE_SYMBOLS
    except ImportError:  # pragma: no cover
        from backtest.paper_config import PAPER_CONFIGS
        from backtest.signals import DO_NOT_TRADE_SYMBOLS

    if symbol in DO_NOT_TRADE_SYMBOLS:
        return True
    cfg = PAPER_CONFIGS.get(symbol)
    return cfg is not None and not cfg.get("enabled", True)


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
        initial_delay_seconds: int = 60,
    ):
        """
        Args:
            trading_pipeline: TradingPipeline instance (from main.py)
            db_manager: DatabaseManager instance for creating approvals
            symbols: List of symbols to scan (default: ["MCL", "MNQ"])
            scan_interval_minutes: How often to scan (default: 60)
            initial_delay_seconds: Wait before the FIRST scan so uvicorn can
                bind port 8010 and /health can respond before the scanner
                starts hammering the data layer. Default 60s. Set to 0 in
                tests. Roadmap P1.8 partial mitigation.
        """
        self.trading_pipeline = trading_pipeline
        self.db_manager = db_manager
        self.symbols = symbols or ["MCL", "MNQ"]
        self.scan_interval_minutes = scan_interval_minutes
        self.initial_delay_seconds = max(0, int(initial_delay_seconds))
        self._paper_tracker = None  # injected post-construction via set_paper_tracker()
        self._safety_layer = None  # injected via set_safety_layer() — kill-switch gate
        self._data_manager = None  # injected via set_data_manager() — entry-price sanity
        # Asset-class map: which scanned symbols are futures. Defaults to ALL
        # symbols (backward-compatible — original callers passed futures only).
        # main.py overrides via set_futures_symbols() once equities are added.
        self._futures_symbols = {str(sym).upper() for sym in self.symbols}

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

    def set_safety_layer(self, safety_layer) -> None:
        """Inject the safety layer so the live opener honors the kill switch.

        Without this, the autonomous paper-mode bypass would auto-execute even
        while the kill switch is active (the scanner loop had no kill-switch gate
        — the APScheduler jobs did, but this background loop did not)."""
        self._safety_layer = safety_layer

    def set_data_manager(self, data_manager) -> None:
        """Inject the market data manager so the live opener can run the
        entry-price sanity check (phantom-price guard) before booking a trade."""
        self._data_manager = data_manager

    def set_futures_symbols(self, futures_symbols) -> None:
        """Declare which scanned symbols are futures contracts. Symbols not in
        this set are treated as equities (OPTIONS_WATCHLIST) and priced /
        analyzed with is_futures=False."""
        self._futures_symbols = {str(sym).upper() for sym in (futures_symbols or [])}

    def _is_futures_symbol(self, symbol: str) -> bool:
        return str(symbol).upper() in self._futures_symbols

    def _kill_switch_active(self) -> bool:
        """Return True if trading is halted. Fails CLOSED: if the safety layer is
        injected but its status cannot be read, treat as halted (refuse to open)."""
        if self._safety_layer is None:
            return False
        try:
            # SafetyLayer.get_status() exposes the latched flag under "is_killed"
            # (safety_router maps it to the public "kill_switch_active" field).
            # Reading the wrong key here silently returned None→False, so the
            # live opener bypassed an active kill switch (TSLA opened 2026-06-15
            # 23:04 UTC under an active switch). Read the canonical key.
            return bool(self._safety_layer.get_status().get("is_killed"))
        except Exception as exc:
            logger.error(
                "[SAFETY] kill-switch status unavailable (%s) — fail-closed (halting)", exc
            )
            return True

    async def _entry_price_is_sane(
        self, symbol: str, entry_price: float, is_futures: bool = True
    ) -> tuple[bool, str]:
        """Phantom-price guard for the live opener. Fails CLOSED under autonomy:
        any error verifying the price rejects the trade rather than letting a
        possibly-corrupted entry through (the 2026-05-09 stop-into-entry incident).

        Returns (True, "") when the check is disabled by feature flag, or when no
        data_manager is injected (cannot verify — logged, allowed for test/bootstrap
        parity). Returns (False, reason) on a failed check OR on an exception."""
        from risk.entry_price_sanity import (
            check_entry_price_sanity,
            is_entry_price_sanity_enabled,
        )

        if not is_entry_price_sanity_enabled():
            return True, ""
        if self._data_manager is None:
            logger.warning(
                "[ENTRY_PRICE_SANITY] %s: no data_manager injected — cannot verify; allowing",
                symbol,
            )
            return True, "no_data_manager"
        try:
            return await check_entry_price_sanity(
                symbol=symbol,
                entry_price=entry_price,
                data_manager=self._data_manager,
                is_futures=is_futures,
            )
        except Exception as exc:
            logger.critical(
                "[ENTRY_PRICE_SANITY] %s check raised (%s) — rejecting (fail-closed)",
                symbol,
                exc,
            )
            return False, f"sanity_check_error: {exc}"

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
        if self._task is None or self._task.done():
            logger.info("[Scanner] Resume requested from dormant state; starting task")
            await self.start()
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
        """
        Background loop — runs until stop() is called.

        Pause-responsiveness (fix 2026-04-10 D2): the inter-scan sleep is
        chunked into 1-minute intervals with an _active check between each.
        This ensures that calling pause() honors the pause within 60 seconds
        instead of the previous behavior where the 60-minute blocking sleep
        would let one extra scan fire after pause() was called. See
        docs/session-logs/diag-2026-04-10-D2-scanner-pause-leak.md.
        """
        logger.info("[Scanner] Background loop started")

        # P1.8 mitigation: defer the first scan so uvicorn can bind port 8010
        # and /health can respond before the scanner starts spawning parallel
        # pipeline runs + TV MCP set-symbol calls that eat the event loop.
        if self.initial_delay_seconds > 0:
            logger.info(
                "[Scanner] Delaying first scan by %ds to let API bind cleanly",
                self.initial_delay_seconds,
            )
            try:
                await asyncio.sleep(self.initial_delay_seconds)
            except asyncio.CancelledError:
                logger.info("[Scanner] Cancelled during initial delay")
                return

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

                # Pause-responsive inter-scan sleep: chunk the long sleep
                # into 1-minute slices so pause() is honored within 60s.
                _sleep_remaining = self.scan_interval_minutes * 60
                while _sleep_remaining > 0:
                    _chunk = min(60, _sleep_remaining)
                    await asyncio.sleep(_chunk)
                    _sleep_remaining -= _chunk
                    if not self._active:
                        logger.info(
                            "[Scanner] Pause detected mid-sleep; exiting "
                            "inter-scan wait with %ds remaining",
                            _sleep_remaining,
                        )
                        break

            except asyncio.CancelledError:
                logger.info("[Scanner] Task cancelled")
                break
            except Exception as e:
                logger.error(f"[Scanner] Unexpected error in loop: {e}", exc_info=True)
                self._error_count += 1
                await asyncio.sleep(60)  # Wait before retry

    async def _run_scan(self) -> None:
        """Execute one complete scan of all symbols concurrently."""
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

        # Run all symbol scans concurrently using asyncio.gather
        tasks = [self._scan_symbol(symbol) for symbol in self.symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any exceptions from individual symbol scans
        for symbol, result in zip(self.symbols, results, strict=False):
            if isinstance(result, Exception):
                logger.error(f"[Scanner] Failed to scan {symbol}: {result}", exc_info=result)
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
            current_time_et >= rth_open and current_time_et < rth_no_entry_start
        ) or (  # First 5 min
            current_time_et >= rth_no_entry_end and current_time_et <= rth_close
        )  # Last 15 min
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

        _is_fut = self._is_futures_symbol(symbol)

        logger.debug(f"[Scanner] Analyzing {symbol} (is_futures={_is_fut})")

        try:
            _t0 = _time_module.monotonic()
            result = await self.trading_pipeline.analyze_and_decide(
                symbol=symbol,
                is_futures=_is_fut,
                timeframe="1h",
            )
            _duration_ms = (_time_module.monotonic() - _t0) * 1000.0

            if not result:
                logger.warning(f"[Scanner] No result for {symbol}")
                return

            final_action = result.get("final_action", "hold")

            # Always persist every pipeline execution to pipeline_runs for audit trail.
            try:
                from approval.pipeline_history import pipeline_run_record_from_result

                _run_record = pipeline_run_record_from_result(
                    symbol=symbol,
                    result=result,
                    duration_ms=_duration_ms,
                    source="scanner",
                )
                self.db_manager.insert_pipeline_run(_run_record)
            except Exception as _db_exc:
                logger.warning("[Scanner] Failed to log pipeline_run for %s: %s", symbol, _db_exc)

            # Also write to the decisions table so /decisions/recent shows scanner results.
            try:
                _conf = float(
                    result.get("confidence")
                    or (result.get("fund_decision") or {}).get("final_conviction")
                    or (result.get("trade_decision") or {}).get("confidence")
                    or 0.0
                )
                _summary = result.get("summary", "")
                _reasoning = (result.get("trade_decision") or {}).get("reasoning", "")
                _regime = (result.get("analyst_reports") or {}).get("technical", {}).get(
                    "regime"
                ) or None
                # Data-truth: stamp *what data* this decision was based on (tier +
                # per-symbol serve-age), matching main.py's _log_decision (PR #286).
                # Additive only — never changes a trade decision, never raises.
                _provenance = build_data_provenance(self._data_manager, symbol)
                _sig = stamp_signal_data({"source": "scanner", "summary": _summary}, _provenance)
                self.db_manager.insert_decision(
                    symbol=symbol,
                    action=final_action,
                    confidence=_conf,
                    regime=_regime,
                    signal_data=_sig,
                    reasoning=_reasoning or _summary,
                    full_pipeline_data=result,
                )
            except Exception as _dec_exc:
                logger.warning("[Scanner] Failed to log decision for %s: %s", symbol, _dec_exc)

            if final_action not in ("buy", "sell"):
                logger.debug(f"[Scanner] {symbol} signal: {final_action}, no action needed")
                return

            # Signal fired.
            quantity = result.get("final_quantity", 1)
            entry_price = result.get("trade_decision", {}).get("entry_price", None)
            snapshot = result

            # Human-approval gate. When approval is OFF (autonomous paper mode),
            # do NOT create a pending_trade_approvals row: nobody approves these,
            # so they only time out and auto-reject, generating misleading
            # "APPROVAL REQUIRED" DMs for trades that never happen. The executed
            # paper trade below is the record of record. Use an ephemeral ref so
            # downstream logging/correlation still works without a DB row.
            try:
                from config import settings as _cfg_appr

                _require_human = bool(_cfg_appr.REQUIRE_HUMAN_APPROVAL)
            except Exception:
                _require_human = True

            if _require_human:
                approval_id = self.db_manager.insert_pending_approval(
                    symbol=symbol,
                    action=final_action,
                    quantity=quantity,
                    entry_price=entry_price,
                    pipeline_snapshot=snapshot,
                    timeframe=snapshot.get("timeframe", "1h"),
                )
                self._approval_count += 1
                logger.info(
                    f"[Scanner] {symbol} signal: {final_action} {quantity} "
                    f"(approval_id={approval_id[:8]})"
                )
            else:
                import uuid as _uuid_auto

                approval_id = f"auto-{_uuid_auto.uuid4().hex[:8]}"
                logger.info(
                    f"[Scanner] {symbol} signal: {final_action} {quantity} "
                    f"(autonomous — no approval row, ref={approval_id})"
                )

            # ── Paper mode bypass: auto-log paper trade without waiting for human approval ──
            # In paper mode the trade is written to the DB immediately so validation data
            # exists. A pending_trade_approvals row is created ONLY when human approval is
            # required (see gate above); under autonomy the executed trade is the record.
            try:
                from config import settings as _cfg

                _is_paper_mode = not _cfg.LIVE_TRADING_ENABLED
            except Exception:
                _is_paper_mode = True

            # Distinct skip reasons so the final log is accurate (not all
            # not-executed paths are "live mode requires human").
            _validation_only_skip = False
            _submission_blocked_reason: str | None = None

            _confidence = float(result.get("confidence", 0.0))

            # ── Validation-only strategy gate ──────────────────────────────────
            # Block paper-mode bypass for strategy signals that have no WFO run
            # or a gate v2 FAIL verdict.  The pending approval row is still
            # created for audit/dashboard visibility; only the automatic
            # paper_tracker write is skipped.
            # Existing open positions are NOT touched — gate blocks NEW submissions only.
            _technical_report_for_gate = (result.get("analyst_reports") or {}).get(
                "technical"
            ) or {}
            _stark_signal = (
                (_technical_report_for_gate.get("indicators") or {}).get("stark_signal") or ""
            ).upper()
            from agents.pipeline import VALIDATION_ONLY_STRATEGIES as _VOL_STRATS

            if _stark_signal and _stark_signal in _VOL_STRATS:
                logger.warning(
                    "[VALIDATION_ONLY] skipping strategy=%s symbol=%s action=%s — "
                    "no WFO run in wfe_snapshots and gate v2 verdict absent. "
                    "Pending approval %s preserved for audit visibility.",
                    _stark_signal,
                    symbol,
                    final_action,
                    approval_id[:8],
                )
                _is_paper_mode = False  # short-circuit the bypass block below
                _validation_only_skip = True

            # Market-hours submission guard: the scan loop only checks futures
            # hours, so an equity signal can reach here after the cash market
            # closed. Hard-gate the auto-submission for equities outside RTH
            # (the 20:24 off-hours stale-fill class). Futures are already
            # covered by the loop-level _is_futures_market_hours() gate.
            if (
                _is_paper_mode
                and not _validation_only_skip
                and _market_hours_submission_guard_enabled()
                and not _is_fut
                and not _is_equity_market_hours()
            ):
                _is_paper_mode = False
                _submission_blocked_reason = "equity_market_closed"

            _executed = False
            _exec_details: dict | None = None
            if _is_paper_mode and self._paper_tracker is not None and entry_price is not None:
                try:
                    trade_dec = result.get("trade_decision") or {}
                    technical_report = (result.get("analyst_reports") or {}).get("technical") or {}
                    fund_decision = result.get("fund_decision") or {}
                    stop_price = trade_dec.get("stop_price") or None
                    # Dedup guard (2026-06-11 incident): the hourly scan re-emits a
                    # persisting trend signal every cycle; without this check the
                    # bypass auto-logged identical duplicate open positions (MES +
                    # MGC entered twice, 00:04 and 01:04). One open paper position
                    # per symbol — skip the auto-log while one exists. The pending
                    # approval above is still created for audit visibility.
                    _open_for_symbol = [
                        p
                        for p in (self._paper_tracker.get_open_positions() or [])
                        if str(p.get("symbol") or "").upper() == str(symbol).upper()
                    ]
                    # Safety gate: never auto-execute a paper trade without a stop.
                    # A position with no stop has undefined risk — refuse it.
                    if stop_price is None:
                        logger.critical(
                            "[SAFETY] paper_mode_bypass BLOCKED for %s %s — "
                            "no stop_loss in trade_decision; refusing auto-execution. "
                            "trade_decision=%r",
                            symbol,
                            final_action,
                            trade_dec,
                        )
                    elif _open_for_symbol:
                        logger.info(
                            "[EXECUTION] symbol=%s action=%s confidence=%.2f threshold=%.2f "
                            "executed=False reason=paper_position_already_open "
                            "open_trade_id=%s approval_id=%s",
                            symbol,
                            final_action,
                            _confidence,
                            0.0,
                            str(_open_for_symbol[0].get("trade_id") or "")[:8],
                            approval_id[:8],
                        )
                    elif self._kill_switch_active():
                        # Autonomy hardening: the live opener now honors the kill
                        # switch. Previously only the APScheduler jobs gated on it;
                        # this background loop would auto-execute regardless.
                        logger.warning(
                            "[EXECUTION] symbol=%s action=%s executed=False "
                            "reason=kill_switch_active approval_id=%s",
                            symbol,
                            final_action,
                            approval_id[:8],
                        )
                    elif _symbol_is_halted_for_scanner(symbol):
                        # GT-52: this bypass never consulted DO_NOT_TRADE_SYMBOLS /
                        # paper_config.enabled before writing a paper trade. Blocks
                        # only the explicit halt list -- equities with no
                        # PAPER_CONFIGS entry are untouched (2026-08-03 decision).
                        logger.critical(
                            "[EXECUTION] symbol=%s action=%s executed=False "
                            "reason=symbol_halted approval_id=%s",
                            symbol,
                            final_action,
                            approval_id[:8],
                        )
                    elif not (
                        _sanity := await self._entry_price_is_sane(
                            symbol, float(entry_price), _is_fut
                        )
                    )[0]:
                        # Fail-closed phantom-price guard on the LIVE path (the
                        # sanity check previously existed only in the enqueue and
                        # manual-approval paths, never here). Computed once via the
                        # walrus binding; _sanity[1] carries the rejection reason.
                        logger.critical(
                            "[EXECUTION] symbol=%s action=%s executed=False "
                            "reason=entry_price_sanity detail=%s approval_id=%s",
                            symbol,
                            final_action,
                            _sanity[1],
                            approval_id[:8],
                        )
                    else:
                        target_price = (
                            trade_dec.get("target_price") or trade_dec.get("take_profit") or None
                        )
                        conviction = fund_decision.get("final_conviction", 0.0) or trade_dec.get(
                            "confidence", 0.0
                        )
                        _indicators = technical_report.get("indicators") or {}
                        stc_val = _indicators.get("stc_value")
                        rv_at_entry = _indicators.get("rv_20_ann_pct")
                        # Persist per-analyst signals so the close path
                        # (_record_agent_feedback) writes a trade_outcomes row
                        # for Brier/IC calibration. Without this the scanner
                        # path silently no-ops at close (tracker.py:880) and
                        # calibration starves.
                        try:
                            from engine.analytics.agent_feedback import (
                                build_analyst_signals_map,
                            )
                        except ImportError:  # pragma: no cover
                            from analytics.agent_feedback import (
                                build_analyst_signals_map,
                            )
                        _scanner_analyst_signals = build_analyst_signals_map(
                            result.get("analyst_reports")
                        )
                        # Entry-price sanity gate (2026-06-12 phantom-price
                        # incident: an MES auto-paper trade was logged at
                        # entry_price=100.5 — an STC oscillator value, 0-100,
                        # had leaked into the price field). The human-approval
                        # path validates entry prices via check_entry_price_sanity
                        # (approval/service.py), but this scanner auto-paper
                        # bypass wrote unchecked. Validate against the SAME
                        # technical-report indicators the decision used
                        # (current_price + ATR) with the pure predicate — no
                        # extra I/O and no data_manager dependency. A definitive
                        # insane verdict BLOCKS the write; an unexpected error in
                        # the check itself fails open (mirrors the approval path)
                        # but logs loudly. Disable via ENABLE_ENTRY_PRICE_SANITY=0.
                        _entry_sane = True
                        try:
                            try:
                                from engine.risk.entry_price_sanity import (
                                    is_entry_price_sane,
                                    is_entry_price_sanity_enabled,
                                )
                            except ImportError:  # pragma: no cover
                                from risk.entry_price_sanity import (
                                    is_entry_price_sane,
                                    is_entry_price_sanity_enabled,
                                )
                            _mkt_ref = _indicators.get("current_price")
                            _atr_ref = _indicators.get("atr")
                            if not is_entry_price_sanity_enabled():
                                pass
                            elif _mkt_ref is None or _atr_ref is None:
                                # No reference to validate against. Fail OPEN
                                # (don't silently halt all auto-paper trades when
                                # an indicator is momentarily absent) but log so
                                # the unvalidated write is visible. In production
                                # current_price + atr are always populated, so the
                                # phantom-price case still gets validated below.
                                logger.warning(
                                    "[ENTRY_PRICE_SANITY] no market/atr reference for %s "
                                    "(current_price=%r atr=%r) — entry %s written "
                                    "UNVALIDATED",
                                    symbol,
                                    _mkt_ref,
                                    _atr_ref,
                                    entry_price,
                                )
                            else:
                                _entry_sane, _sane_reason = is_entry_price_sane(
                                    symbol=symbol,
                                    entry_price=float(entry_price),
                                    market_price=_mkt_ref,
                                    atr=_atr_ref,
                                )
                                if not _entry_sane:
                                    logger.critical(
                                        "[SAFETY] paper_mode_bypass BLOCKED for %s %s — "
                                        "entry-price sanity failed: %s",
                                        symbol,
                                        final_action,
                                        _sane_reason,
                                    )
                        except Exception as _sane_exc:  # pragma: no cover
                            # Unexpected error in the check must not crash the
                            # scan loop; fail open so a check-machinery bug can't
                            # silently halt all auto-paper trades — but log it.
                            logger.error(
                                "[ENTRY_PRICE_SANITY] scanner check errored for %s: %s "
                                "— allowing write",
                                symbol,
                                _sane_exc,
                            )
                            _entry_sane = True
                        if _entry_sane:
                            trade_id_inner = self._paper_tracker.add_paper_trade(
                                symbol=symbol,
                                side=final_action,
                                quantity=float(quantity) if quantity else 1.0,
                                entry_price=float(entry_price),
                                stop_loss=float(stop_price),
                                take_profit=float(target_price) if target_price else None,
                                strategy_params={
                                    "source": "scanner",
                                    "approval_id": approval_id,
                                    # Persist the Stark TPO signal so DB consumers
                                    # (gapfill_options_papertrack.py, strategy
                                    # attribution) can identify which production
                                    # signal drove the trade — previously this was
                                    # only transient in the technical report.
                                    "stark_signal": _stark_signal or None,
                                    "conviction": round(float(conviction), 4),
                                    "direction": final_action.upper(),
                                    "summary": result.get("summary", ""),
                                    "regime": technical_report.get("regime") or "unknown",
                                    "bias": technical_report.get("trend")
                                    or technical_report.get("bias")
                                    or "unknown",
                                    "entry_stc_value": (
                                        round(float(stc_val), 2) if stc_val is not None else None
                                    ),
                                    "pipeline_conviction": round(float(conviction), 4),
                                    "predicted_direction": final_action.upper(),
                                    "rv_at_entry": (
                                        round(float(rv_at_entry), 4)
                                        if rv_at_entry is not None
                                        else None
                                    ),
                                    "analyst_signals": _scanner_analyst_signals,
                                },
                            )
                            logger.info(
                                "[EXECUTION] symbol=%s action=%s confidence=%.2f threshold=%.2f "
                                "executed=True reason=paper_mode_bypass trade_id=%s",
                                symbol,
                                final_action,
                                _confidence,
                                0.0,
                                trade_id_inner[:8],
                            )
                            _executed = True
                            _exec_details = {
                                "trade_id": trade_id_inner,
                                "quantity": float(quantity) if quantity else 1.0,
                                "entry_price": float(entry_price),
                                "stop_price": float(stop_price),
                                "target_price": float(target_price) if target_price else None,
                            }
                except Exception as _paper_exc:
                    logger.error(
                        "[Scanner] Paper trade auto-log failed for %s: %s", symbol, _paper_exc
                    )
            elif _submission_blocked_reason is not None:
                logger.info(
                    "[EXECUTION] symbol=%s action=%s confidence=%.2f threshold=%.2f "
                    "executed=False reason=%s approval_id=%s",
                    symbol,
                    final_action,
                    _confidence,
                    0.0,
                    _submission_blocked_reason,
                    approval_id[:8],
                )
            elif _validation_only_skip:
                logger.info(
                    "[EXECUTION] symbol=%s action=%s confidence=%.2f threshold=%.2f "
                    "executed=False reason=validation_only_strategy_skipped approval_id=%s",
                    symbol,
                    final_action,
                    _confidence,
                    0.0,
                    approval_id[:8],
                )
            elif not _is_paper_mode:
                logger.info(
                    "[EXECUTION] symbol=%s action=%s confidence=%.2f threshold=%.2f "
                    "executed=False reason=live_mode_requires_human approval_id=%s",
                    symbol,
                    final_action,
                    _confidence,
                    0.0,
                    approval_id[:8],
                )
            else:
                logger.warning(
                    "[EXECUTION] symbol=%s action=%s confidence=%.2f threshold=%.2f "
                    "executed=False reason=paper_tracker_not_available",
                    symbol,
                    final_action,
                    _confidence,
                    0.0,
                )

            # ── Alerting (full visibility) ─────────────────────────────────
            # When the trade actually executed under autonomy, fire a TRUE
            # "trade opened" confirmation (entry/stop/target) — not the legacy
            # "APPROVAL REQUIRED / approve at localhost:3010" prompt, which is
            # misleading when no human approval is in the loop.
            if _executed:
                try:
                    from notifications.openclaw_notifier import notify_trade_opened

                    _d = _exec_details or {}
                    await notify_trade_opened(
                        symbol=symbol,
                        action=final_action,
                        quantity=_d.get("quantity", float(quantity) if quantity else 1.0),
                        entry_price=_d.get("entry_price", float(entry_price)),
                        stop_price=_d.get("stop_price"),
                        target_price=_d.get("target_price"),
                        source="scanner",
                    )
                except Exception as _open_err:
                    logger.warning("trade-opened alert failed for %s: %s", symbol, _open_err)
            else:
                # Not executed. Only show the human-approval prompt when approval
                # is actually required; otherwise (blocked by a safety gate under
                # autonomy) emit a plain signal alert for visibility without the
                # spurious "approve" call-to-action.
                try:
                    from config import settings as _cfg_n

                    _require_human = bool(_cfg_n.REQUIRE_HUMAN_APPROVAL)
                except Exception:
                    _require_human = True

                if _require_human:
                    try:
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
                    except Exception as _pa_err:
                        logger.debug("pending-approval notify skipped: %s", _pa_err)

                    # Legacy "JARVIS SIGNAL ... Approve at localhost:3010" alert —
                    # only meaningful when a human actually approves. Under autonomy
                    # a not-executed signal is a safety-gate block or a dedup/no-stop
                    # skip; those are logged, not DM'd, so the hourly persisting
                    # signal no longer spams "approve a trade that never happens".
                    try:
                        from notifications.openclaw_notifier import notify_signal as _oc_signal

                        await _oc_signal(
                            symbol=symbol,
                            action=final_action,
                            confidence=float(result.get("confidence", 0.0)),
                            reason=str(result.get("reason", "")),
                            market="futures" if _is_fut else "equity",
                        )
                    except Exception as _oc_err:
                        logger.debug(f"OpenClaw signal notification skipped: {_oc_err}")

        except Exception as e:
            logger.error(f"[Scanner] Pipeline error for {symbol}: {e}", exc_info=True)
            self._error_count += 1
