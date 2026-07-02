"""
JARVIS TRADER — End-of-Day Scheduler
Records daily P&L snapshots at market close and runs EOD analysis.

Schedule
--------
* EOD snapshot  : 3:05 PM CT (20:05 UTC) Mon–Fri — captures final daily P&L
* Weekly review : 3:30 PM CT (20:30 UTC) Friday  — 5-day rolling summary
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis_trader.eod_scheduler")

# Starting balance used when no prior DB record exists (paper trading default)
_DEFAULT_STARTING_BALANCE = 10_000.0


async def _check_wfe_decay(symbol: str, wfe_value: float) -> None:
    """Fire alert if WFE drops below decay thresholds."""
    if wfe_value >= 0.50:
        return  # WFE healthy — no alert needed

    if wfe_value < 0.30:
        severity = "CRITICAL"
        msg = (
            f"CRITICAL: {symbol} WFE dropped to {wfe_value:.2f} — below 0.30 fail threshold. "
            f"Strategy edge has degraded. Manual review required. Trading should be halted."
        )
    else:
        severity = "WARNING"
        msg = (
            f"WARNING: {symbol} WFE is {wfe_value:.2f} — below 0.50 warn threshold. "
            f"Strategy edge is weakening. Monitor closely."
        )

    logger.warning(
        "[EOD] WFE decay alert for %s: severity=%s wfe=%.2f", symbol, severity, wfe_value
    )

    # Discord alert
    try:
        from notifications.discord_notifier import discord_validation_alert

        await discord_validation_alert(
            gate_name=f"wfe_decay_{symbol.lower()}",
            old_status="PASS",
            new_status=severity,
            current_value=wfe_value,
            target_value=0.50,
        )
    except Exception as exc:
        logger.debug("[EOD] Discord WFE alert failed (non-fatal): %s", exc)

    # WhatsApp / OpenClaw alert
    try:
        from notifications.openclaw_notifier import send_raw

        await send_raw(msg)
    except Exception as exc:
        logger.debug("[EOD] OpenClaw WFE alert failed (non-fatal): %s", exc)


async def _save_wfe_snapshots() -> None:
    """Save WFE snapshots for paper-validated instruments via the engine API."""
    import httpx

    from config import TradingConfig

    config = TradingConfig()
    for symbol in ["MCL", "MNQ"]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "http://localhost:8010/wfe/snapshot",
                    params={"symbol": symbol},
                    headers={"X-API-Key": config.API_KEY},
                    timeout=30.0,
                )
                logger.info("[EOD] WFE snapshot saved for %s: %s", symbol, resp.status_code)
                # Check for WFE decay in the snapshot response
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        wfe_val = data.get("wfe_score") or data.get("wfe") or data.get("value")
                        if wfe_val is not None:
                            await _check_wfe_decay(symbol, float(wfe_val))
                    except Exception as _parse_exc:
                        logger.debug(
                            "[EOD] WFE decay check parse error for %s: %s", symbol, _parse_exc
                        )
        except Exception as exc:
            logger.warning("[EOD] WFE snapshot failed for %s: %s", symbol, exc)


class EODScheduler:
    """
    End-of-Day P&L snapshot and weekly review scheduler.

    Designed to plug into the existing APScheduler instance created in
    ``engine/main.py``.  All dependencies are optional — the scheduler
    degrades gracefully if db_manager, portfolio_tracker, or
    whatsapp_notifier are not provided.

    Parameters
    ----------
    db_manager:
        ``DatabaseManager`` instance from ``engine/database/schema.py``.
    portfolio_tracker:
        ``PortfolioTracker`` instance from ``engine/portfolio/tracker.py``.
    whatsapp_notifier:
        ``WhatsAppNotifier`` instance from ``engine/notifications/whatsapp.py``.
    """

    def __init__(
        self,
        db_manager: Any = None,
        portfolio_tracker: Any = None,
        whatsapp_notifier: Any = None,
        learning_consolidator: Any = None,
        capital_allocator: Any = None,
        market_price_fn: Any = None,
    ) -> None:
        """
        Parameters
        ----------
        market_price_fn : Callable[[str], Optional[float]], optional
            Per-symbol last-known price fetcher used by ``run_session_flatten``
            to close each open position at a real market price instead of
            defaulting to entry_price (the 2026-04-23 Phase-3 metrics bug).
            When None, flatten falls back to entry_price and logs ERROR so
            the condition is visible.
        """
        self._db = db_manager
        self._tracker = portfolio_tracker
        self._notifier = whatsapp_notifier
        self._consolidator = learning_consolidator
        self._capital_allocator = capital_allocator
        self._market_price_fn = market_price_fn
        self._alert_manager = None  # Injected by main.py after ValidationAlertManager is created
        logger.info(
            "EODScheduler initialised — db=%s tracker=%s whatsapp=%s consolidator=%s allocator=%s market_price_fn=%s",
            "yes" if self._db else "no",
            "yes" if self._tracker else "no",
            "yes" if self._notifier else "no",
            "yes" if self._consolidator else "no",
            "yes" if self._capital_allocator else "no",
            "yes" if self._market_price_fn else "no",
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _today_date_str(self) -> str:
        """Return today's date in CT (UTC-5/6) as YYYY-MM-DD."""
        # Use UTC-6 (CST, conservative) — if running during CDT the date is still correct
        ct_now = datetime.now(timezone.utc) - timedelta(hours=6)
        return ct_now.strftime("%Y-%m-%d")

    def _get_starting_balance(self, today: str) -> float:
        """
        Determine today's starting balance.

        Priority:
        1. Yesterday's ending_balance from daily_pnl table
        2. _DEFAULT_STARTING_BALANCE fallback
        """
        if self._db is None:
            return _DEFAULT_STARTING_BALANCE

        try:
            latest = self._db.get_latest_daily_pnl()
            if latest and latest.get("date") != today:
                return float(latest.get("ending_balance", _DEFAULT_STARTING_BALANCE))
        except Exception as exc:
            logger.warning("Could not fetch latest daily P&L from DB: %s", exc)

        return _DEFAULT_STARTING_BALANCE

    def _collect_tracker_metrics(self, today: str) -> Dict[str, Any]:
        """
        Pull today's performance metrics from the portfolio tracker.

        Returns a dict with keys:
            realized_pnl, unrealized_pnl, total_trades,
            winning_trades, losing_trades, max_drawdown
        """
        defaults: Dict[str, Any] = {
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "max_drawdown": 0.0,
        }

        if self._tracker is None:
            return defaults

        try:
            perf = self._tracker.get_performance()
        except Exception as exc:
            logger.error("get_performance() failed: %s", exc)
            return defaults

        total_pnl: float = perf.get("total_pnl", 0.0)
        num_trades: int = perf.get("num_trades", 0)
        win_rate: float = perf.get("win_rate", 0.0)
        winning_trades = int(round(num_trades * win_rate))
        losing_trades = max(0, num_trades - winning_trades)

        # Unrealized P&L: sum P&L of all currently open positions
        unrealized_pnl = 0.0
        try:
            open_positions: List[dict] = self._tracker.get_positions()
            for pos in open_positions:
                current_price = pos.get("current_price") or pos.get("entry_price") or 0.0
                entry_price = pos.get("entry_price") or 0.0
                quantity = pos.get("quantity") or 0.0
                side = (pos.get("side") or pos.get("action") or "buy").lower()
                if "sell" in side or "short" in side:
                    unrealized_pnl += (entry_price - current_price) * abs(quantity)
                else:
                    unrealized_pnl += (current_price - entry_price) * abs(quantity)
        except Exception as exc:
            logger.warning("Could not compute unrealized P&L: %s", exc)

        return {
            "realized_pnl": round(total_pnl, 4),
            "unrealized_pnl": round(unrealized_pnl, 4),
            "total_trades": num_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "max_drawdown": round(perf.get("max_dd", 0.0), 4),
        }

    def _collect_db_trade_metrics(self, today: str) -> Optional[Dict[str, Any]]:
        """
        Derive daily P&L metrics from CLOSED ``paper_trades`` rows — the
        round-trip source of truth — instead of in-memory tracker lifetime
        aggregates.

        Anchoring every balance to initial capital + cumulative closed P&L
        means a corrupted daily_pnl row can never chain into later rows (the
        2026-06 corruption propagated through yesterday's-ending lookups
        after a single basis-flipped write).

        Returns None when the DB or query is unavailable so callers can fall
        back to the legacy tracker path.
        """
        if self._db is None or not hasattr(self._db, "get_trade_history"):
            return None
        try:
            closed = self._db.get_trade_history(limit=5000, status="closed")
        except Exception as exc:
            logger.error("[EOD] get_trade_history failed: %s", exc)
            return None

        cum_before = 0.0
        cum_through = 0.0
        day_trades = day_wins = day_losses = 0
        for t in closed:
            exit_date = str(t.get("exit_time") or "")[:10]
            if not exit_date:
                continue
            pnl = float(t.get("pnl") or 0.0)
            if exit_date < today:
                cum_before += pnl
            if exit_date <= today:
                cum_through += pnl
            if exit_date == today:
                day_trades += 1
                if pnl > 0:
                    day_wins += 1
                elif pnl < 0:
                    day_losses += 1

        return {
            "cum_realized_before": round(cum_before, 4),
            "cum_realized_through": round(cum_through, 4),
            "total_trades": day_trades,
            "winning_trades": day_wins,
            "losing_trades": day_losses,
        }

    def _build_paper_performance_by_symbol(self) -> Dict[str, Dict[str, float]]:
        """
        Build {symbol: {"sharpe": float, "current_allocation": float}} from
        the portfolio tracker's closed-trade performance data.

        Returns an empty dict when no tracker is available or no trades exist.
        """
        if self._tracker is None:
            return {}

        try:
            perf = self._tracker.get_performance()
        except Exception as exc:
            logger.warning("[EOD] Could not fetch performance for rebalance: %s", exc)
            return {}

        # get_performance() may return per-symbol breakdown or a flat dict.
        # Try per-symbol first; fall back to applying flat Sharpe to known symbols.
        by_symbol: Dict[str, Dict[str, float]] = {}

        symbol_breakdown = perf.get("by_symbol") or perf.get("symbols") or {}
        if isinstance(symbol_breakdown, dict) and symbol_breakdown:
            for sym, sym_perf in symbol_breakdown.items():
                by_symbol[sym] = {
                    "sharpe": float(sym_perf.get("sharpe", 0.0) or 0.0),
                    "current_allocation": float(sym_perf.get("allocation", 0.25) or 0.25),
                }
        else:
            # Flat performance dict — apply to known active instruments
            flat_sharpe = float(perf.get("sharpe", 0.0) or 0.0)
            for sym in ("MCL", "MNQ", "MES", "MGC"):
                by_symbol[sym] = {
                    "sharpe": flat_sharpe,
                    "current_allocation": 0.25,
                }

        return by_symbol

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_eod_snapshot(self) -> Dict[str, Any]:
        """
        Record an end-of-day P&L snapshot.

        Called automatically at 3:05 PM CT (20:05 UTC) on weekdays by the
        APScheduler job registered via ``register_with_scheduler()``.

        Returns
        -------
        dict
            The snapshot data that was written to the database, plus a
            ``"status"`` key (``"ok"`` or ``"error"``).
        """
        today = self._today_date_str()
        logger.info("[EOD] Running end-of-day snapshot for %s", today)

        metrics = self._collect_tracker_metrics(today)
        unrealized_pnl: float = metrics["unrealized_pnl"]

        # 2026-06-12 corruption fix: anchor balances to initial capital +
        # cumulative CLOSED paper_trades P&L (the round-trip source of truth)
        # instead of chaining off yesterday's daily_pnl row and lifetime
        # tracker aggregates. A single basis-flipped row used to propagate
        # phantom ±$40k "realized" days through the starting-balance lookup;
        # with absolute anchoring the table is a pure derivation and cannot
        # drift even if a bad row exists.
        db_metrics = self._collect_db_trade_metrics(today)
        if db_metrics is not None:
            starting_balance = round(
                _DEFAULT_STARTING_BALANCE + db_metrics["cum_realized_before"], 4
            )
            ending_balance = round(
                _DEFAULT_STARTING_BALANCE + db_metrics["cum_realized_through"], 4
            )
            realized_pnl = round(ending_balance - starting_balance, 4)
            total_trades = db_metrics["total_trades"]
            winning_trades = db_metrics["winning_trades"]
            losing_trades = db_metrics["losing_trades"]
        else:
            # Legacy fallback (no DB): lifetime tracker anchor + daily delta.
            starting_balance = self._get_starting_balance(today)
            lifetime_pnl: float = metrics["realized_pnl"]
            ending_balance = round(_DEFAULT_STARTING_BALANCE + lifetime_pnl, 4)
            realized_pnl = round(ending_balance - starting_balance, 4)
            total_trades = metrics["total_trades"]
            winning_trades = metrics["winning_trades"]
            losing_trades = metrics["losing_trades"]

        snapshot = {
            "date": today,
            "starting_balance": starting_balance,
            "ending_balance": ending_balance,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "max_drawdown": metrics["max_drawdown"],
        }

        # Persist to database
        if self._db is not None:
            try:
                written = self._db.upsert_daily_pnl(
                    date=snapshot["date"],
                    starting_balance=snapshot["starting_balance"],
                    ending_balance=snapshot["ending_balance"],
                    realized_pnl=snapshot["realized_pnl"],
                    unrealized_pnl=snapshot["unrealized_pnl"],
                    total_trades=snapshot["total_trades"],
                    winning_trades=snapshot["winning_trades"],
                    losing_trades=snapshot["losing_trades"],
                    max_drawdown=snapshot["max_drawdown"],
                )
                if written is False:
                    # Plausibility guard refused the row — surface loudly.
                    logger.error("[EOD] Snapshot REFUSED by daily_pnl write guard")
                    snapshot["status"] = "refused"
                    return snapshot
                logger.info(
                    "[EOD] Snapshot saved — date=%s realized=%+.2f unrealized=%+.2f trades=%d",
                    today,
                    realized_pnl,
                    unrealized_pnl,
                    snapshot["total_trades"],
                )
                snapshot["status"] = "ok"
            except Exception as exc:
                logger.error("[EOD] DB upsert failed: %s", exc)
                snapshot["status"] = "error"
                snapshot["error"] = str(exc)
        else:
            logger.warning("[EOD] No db_manager — snapshot not persisted")
            snapshot["status"] = "no_db"

        # Phantom detector (2026-07-02) — flag-only. Scan the closed ledger for
        # suspicious trades (duplicate bookings, pnl/price inconsistency,
        # contaminated-entry outliers) so Amo gets a fresh, evidence-tagged list
        # to confirm-mark (mark_phantom_trades.py) BEFORE the next snapshot trusts
        # them. It never mutates a row and never blocks the EOD flow; it only
        # attaches the list to the snapshot and logs it. The list shrinks
        # automatically as suspects are marked phantom (excluded next run).
        if self._db is not None and hasattr(self._db, "get_trade_history"):
            try:
                from analytics.phantom_detector import (
                    detect_suspect_closed_trades,
                    format_suspect_report,
                )

                suspects = detect_suspect_closed_trades(self._db)
                snapshot["suspects"] = [s.as_dict() for s in suspects]
                if suspects:
                    logger.warning("[EOD] %s", format_suspect_report(suspects))
                else:
                    logger.info("[EOD] phantom-detector: 0 suspect closed trades.")
            except Exception as exc:
                logger.error("[EOD] phantom detector failed: %s", exc)

        # Self-heal historical drift (2026-07-02). A phantom/duplicate trade is
        # often reclassified (manual mark_phantom_trades.py) DAYS after it was
        # booked status='closed' and counted by an EOD snapshot. The detective
        # control (reconcile_daily_pnl) then flags the now-stale rows; here we
        # apply the corrective control so the table self-corrects on the next EOD
        # run — rebuilding drifted rows from the closed ledger with the same
        # anchoring this writer uses. DB-only, reversible, idempotent, and never
        # blocks the EOD flow (a heal failure is logged, not raised). NOTE: a
        # heal zeroes the reporting-only max_drawdown/unrealized columns on
        # rebuilt rows (per-day intraday DD isn't reconstructable from EOD closed
        # rows); nothing load-bearing reads them (the kill-switch uses
        # portfolio_equity, not daily_pnl.max_drawdown).
        if self._db is not None and hasattr(self._db, "reconcile_daily_pnl"):
            try:
                recon = self._db.reconcile_daily_pnl()
                if not recon.get("ok", True):
                    repair = self._db.repair_daily_pnl(
                        initial_capital=_DEFAULT_STARTING_BALANCE, dry_run=False
                    )
                    logger.warning(
                        "[EOD] daily_pnl drift on %d date(s) — self-heal %s "
                        "(%d rows changed, %d orphans removed, final_ending=%.2f)",
                        recon.get("drift_count", 0),
                        "APPLIED" if repair.get("applied") else "no-op",
                        repair.get("rows_changed", 0),
                        repair.get("orphans_removed", 0),
                        repair.get("final_ending", 0.0),
                    )
                    snapshot["self_heal"] = repair
            except Exception as exc:
                logger.error("[EOD] daily_pnl self-heal failed: %s", exc)

        # Send WhatsApp EOD summary
        if self._notifier is not None:
            try:
                await self._send_eod_whatsapp(snapshot)
            except Exception as exc:
                logger.warning("[EOD] WhatsApp notification failed: %s", exc)

        # Send Discord EOD summary
        try:
            from notifications.discord_notifier import discord_eod_summary

            await discord_eod_summary(
                total_trades=snapshot["total_trades"],
                wins=snapshot["winning_trades"],
                losses=snapshot["losing_trades"],
                daily_pnl=snapshot["realized_pnl"],
            )
        except Exception as exc:
            logger.warning("[EOD] Discord EOD summary failed: %s", exc)

        # Evaluate validation gates (30-day paper trading targets)
        if self._alert_manager is not None:
            try:
                # Build metrics dict for validation alert manager
                metrics = {
                    "profit_factor": snapshot.get("profit_factor", 0.0),
                    "sharpe_ratio": snapshot.get("sharpe_ratio", 0.0),
                    "win_rate_pct": snapshot.get("win_rate_pct", 0.0),
                    "total_trades": snapshot.get("total_trades", 0),
                    "max_drawdown_pct": snapshot.get("max_drawdown", 0.0),
                    "days_active": snapshot.get("days_active", 0),
                }
                alerts = self._alert_manager.evaluate_gates(metrics)
                if alerts:
                    logger.info(
                        f"[EOD] Validation gate alerts: {len(alerts)} status changes detected"
                    )
            except Exception as exc:
                logger.warning("[EOD] Validation gate evaluation failed: %s", exc)

        # Run memory consolidation at EOD
        if self._consolidator is not None:
            try:
                consolidation_result = await self._consolidator.consolidate_daily(target_date=today)
                logger.info(
                    "[EOD] Memory consolidation complete: %d patterns from %d trades",
                    consolidation_result.get("patterns_extracted", 0),
                    consolidation_result.get("trades_analyzed", 0),
                )
            except Exception as exc:
                logger.warning("[EOD] Memory consolidation failed: %s", exc)

        # Save WFE snapshots for paper-validated instruments
        await _save_wfe_snapshots()

        # Dynamic capital reallocation based on 30-day Sharpe per instrument
        if self._capital_allocator is not None:
            try:
                paper_perf = self._build_paper_performance_by_symbol()
                if paper_perf:
                    new_allocations = self._capital_allocator.rebalance(paper_perf)
                    logger.info("[EOD] Capital rebalance complete: %s", new_allocations)
                else:
                    logger.info("[EOD] Capital rebalance skipped — no performance data available")
            except Exception as exc:
                logger.warning("[EOD] Capital rebalance failed (non-fatal): %s", exc)

        return snapshot

    async def run_weekly_review(self) -> Dict[str, Any]:
        """
        Compute and return a 5-trading-day rolling performance summary.

        Called automatically at 3:30 PM CT (20:30 UTC) on Fridays by the
        APScheduler job registered via ``register_with_scheduler()``.

        Returns
        -------
        dict
            Weekly stats: total_pnl, win_rate, profit_factor, num_trades,
            daily_rows (list of 5 most recent daily_pnl rows), status.
        """
        today = self._today_date_str()
        five_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=7)  # 7 calendar days covers 5 trading days
        ).strftime("%Y-%m-%d")

        logger.info("[EOD] Running weekly review (since %s)", five_days_ago)

        daily_rows: List[dict] = []
        if self._db is not None:
            try:
                daily_rows = self._db.get_daily_pnl(
                    start_date=five_days_ago,
                    end_date=today,
                )
            except Exception as exc:
                logger.error("[EOD] Weekly review DB fetch failed: %s", exc)

        # Aggregate weekly stats
        total_pnl = round(sum(r.get("realized_pnl", 0.0) for r in daily_rows), 4)
        total_trades = sum(r.get("total_trades", 0) for r in daily_rows)
        total_winning = sum(r.get("winning_trades", 0) for r in daily_rows)
        win_rate = round(total_winning / total_trades, 4) if total_trades > 0 else 0.0

        # Profit factor across the week
        total_losing = sum(r.get("losing_trades", 0) for r in daily_rows)
        profit_factor: Optional[float] = None
        if total_losing > 0 and total_winning > 0:
            # Approximate using win/loss counts (detailed trade-level data would be more accurate)
            profit_factor = round(total_winning / total_losing, 4)

        # Max drawdown across the week (worst single day)
        max_drawdown = round(
            min((r.get("max_drawdown", 0.0) for r in daily_rows), default=0.0),
            4,
        )

        summary = {
            "week_ending": today,
            "trading_days": len(daily_rows),
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_trades": total_trades,
            "winning_trades": total_winning,
            "losing_trades": total_losing,
            "max_drawdown": max_drawdown,
            "daily_rows": daily_rows,
            "status": "ok",
        }

        logger.info(
            "[EOD] Weekly review — %d trading days | P&L %+.2f | win_rate %.1f%% | %d trades",
            len(daily_rows),
            total_pnl,
            win_rate * 100,
            total_trades,
        )

        # Send WhatsApp weekly summary
        if self._notifier is not None:
            try:
                await self._send_weekly_whatsapp(summary)
            except Exception as exc:
                logger.warning("[EOD] Weekly WhatsApp notification failed: %s", exc)

        return summary

    def get_today_summary(self) -> Dict[str, Any]:
        """
        Return a real-time intraday P&L summary without writing to the DB.

        Safe to call at any time during the trading day.  Returns the same
        shape as ``run_eod_snapshot()`` but with ``status="intraday"`` and
        no database side effects.
        """
        today = self._today_date_str()
        metrics = self._collect_tracker_metrics(today)
        unrealized_pnl: float = metrics["unrealized_pnl"]

        # Same paper_trades anchoring as run_eod_snapshot (2026-06-12 fix).
        db_metrics = self._collect_db_trade_metrics(today)
        if db_metrics is not None:
            starting_balance = round(
                _DEFAULT_STARTING_BALANCE + db_metrics["cum_realized_before"], 4
            )
            ending_balance = round(
                _DEFAULT_STARTING_BALANCE + db_metrics["cum_realized_through"], 4
            )
            realized_pnl = round(ending_balance - starting_balance, 4)
            total_trades = db_metrics["total_trades"]
            winning_trades = db_metrics["winning_trades"]
            losing_trades = db_metrics["losing_trades"]
        else:
            starting_balance = self._get_starting_balance(today)
            lifetime_pnl: float = metrics["realized_pnl"]
            ending_balance = round(_DEFAULT_STARTING_BALANCE + lifetime_pnl, 4)
            realized_pnl = round(ending_balance - starting_balance, 4)
            total_trades = metrics["total_trades"]
            winning_trades = metrics["winning_trades"]
            losing_trades = metrics["losing_trades"]

        return {
            "date": today,
            "starting_balance": starting_balance,
            "ending_balance": ending_balance,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": round(realized_pnl + unrealized_pnl, 4),
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "max_drawdown": metrics["max_drawdown"],
            "status": "intraday",
        }

    async def run_morning_briefing(self) -> Dict[str, Any]:
        """
        Send the WhatsApp morning briefing ~5 minutes before RTH open.

        Called automatically at 8:25 AM CT (Mon–Fri) by the APScheduler
        job registered via ``register_with_scheduler()``.

        Returns
        -------
        dict
            ``{"sent": bool, "status": "ok" | "no_notifier" | "error", ...}``
        """
        logger.info("[Morning] Running morning briefing job")

        if self._notifier is None or not getattr(self._notifier, "enabled", False):
            logger.info("[Morning] WhatsApp notifier not configured — skipping briefing")
            return {"sent": False, "status": "no_notifier"}

        try:
            import pytz

            from notifications.whatsapp import format_morning_briefing

            ct = pytz.timezone("America/Chicago")
            now_ct = datetime.now(timezone.utc).astimezone(ct)
            session_info = {"day_of_week": now_ct.strftime("%A")}

            # Open positions
            positions: List[dict] = []
            if self._tracker is not None:
                try:
                    positions = self._tracker.get_positions()
                except Exception as exc:
                    logger.warning("[Morning] Could not fetch positions: %s", exc)

            # Yesterday's P&L
            yesterday_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            yesterday_pnl: Optional[Dict[str, Any]] = None
            if self._db is not None:
                try:
                    rows = self._db.get_daily_pnl(days=2)
                    yesterday_pnl = next(
                        (r for r in rows if r.get("date", "").startswith(yesterday_str[:10])),
                        None,
                    )
                except Exception as exc:
                    logger.warning("[Morning] Could not fetch yesterday P&L: %s", exc)

            # Circuit breaker snapshot (best-effort)
            cb_status: Dict[str, Any] = {}
            try:
                if hasattr(self._notifier, "_safety_layer"):
                    cb_status = self._notifier._safety_layer.check_circuit_breakers()
            except Exception:
                pass  # cb_status stays empty — formatter handles missing keys gracefully

            msg = format_morning_briefing(
                session_info=session_info,
                positions=positions,
                daily_pnl=yesterday_pnl,
                circuit_breakers=cb_status,
            )

            sent = await self._notifier.send(msg)
            logger.info("[Morning] Briefing sent=%s", sent)
            return {"sent": sent, "status": "ok"}

        except Exception as exc:
            logger.error("[Morning] Briefing job failed: %s", exc)
            return {"sent": False, "status": "error", "error": str(exc)}

    async def run_vix_alert_check(self) -> None:
        """Check VIX and send WhatsApp alert if above key thresholds."""
        try:
            from analytics.vix_overlay import VIXOverlay

            state = VIXOverlay().get_state()

            if state.vix_value < 20:
                return  # nothing to alert

            thresholds = [
                (40, "EXTREME", "Consider halting all trading"),
                (30, "ELEVATED", "Reduce position size"),
                (20, "CAUTION", "Monitor closely"),
            ]
            for level, label, advice in thresholds:
                if state.vix_value >= level:
                    msg = f"VIX Alert: {state.vix_value:.1f} ({label})\n{advice}\nJARVIS TRADER"
                    await self._notifier.send(msg)
                    break
        except Exception as e:
            logging.getLogger(__name__).error(f"VIX alert check failed: {e}")

    async def run_forward_test_snapshot(self) -> Dict[str, Any]:
        """Run the read-only forward-test loop over the locked candidate registry.

        Read-only: reads closed trades and writes only the forward-test report
        files (gitignored runtime output). It does NOT touch execution, orders,
        or scheduler state — it answers "is any held candidate graduating on its
        forward paper record yet?" once per day so the cockpit pane and any
        alerting have a fresh verdict. A graduation is surfaced via the notifier
        (best-effort); everything else is logged.
        """
        logger.info("[ForwardTest] Running daily forward-test snapshot")
        try:
            from backtest.forward_test import run_forward_test

            report = run_forward_test(db=self._db, persist=True)
        except Exception as exc:
            logger.error("[ForwardTest] snapshot failed: %s", exc, exc_info=True)
            return {"status": "error", "error": str(exc)}

        n_active = report.get("n_active_candidates", 0)
        n_grad = report.get("n_graduated", 0)
        logger.info(
            "[ForwardTest] snapshot ok — %d active candidate(s), %d graduated",
            n_active,
            n_grad,
        )

        # Surface a graduation loudly — it is the whole point of the loop and is
        # rare. Best-effort; a notifier failure must not fail the job.
        if n_grad > 0 and self._notifier is not None and getattr(self._notifier, "enabled", False):
            try:
                grads = [
                    c.get("id", "?") for c in report.get("candidates", []) if c.get("graduated")
                ]
                msg = (
                    "JARVIS forward-test: "
                    f"{n_grad} candidate(s) GRADUATED -> {', '.join(grads)}\n"
                    "A held candidate now clears the registry forward rule."
                )
                await self._notifier.send(msg)
            except Exception as exc:
                logger.warning("[ForwardTest] graduation notify failed: %s", exc)

        return {"status": "ok", "n_active_candidates": n_active, "n_graduated": n_grad}

    async def run_session_flatten(self) -> None:
        """Flatten all open positions at end of session (3:45 PM ET = 20:45 UTC)."""
        logger.info("[EODScheduler] Session flatten triggered — closing all open positions")
        if self._tracker is None:
            logger.warning("[EODScheduler] session_flatten: no paper_tracker available")
            return

        try:
            if not hasattr(self._tracker, "flatten_all_positions"):
                logger.warning("[EODScheduler] flatten_all_positions not available on tracker")
                return

            flatten_kwargs: Dict[str, Any] = {}
            if self._market_price_fn is not None:
                if asyncio.iscoroutinefunction(self._market_price_fn):
                    # Async fetcher (e.g. MarketDataManager.get_current_price): we
                    # can't call it from inside flatten_all_positions (sync) while
                    # the APScheduler loop is already running, so pre-snapshot each
                    # open symbol's price into a dict and hand flatten a sync
                    # lookup closure.
                    snapshot: Dict[str, Optional[float]] = {}
                    open_positions = (
                        self._tracker.get_open_positions()
                        if hasattr(self._tracker, "get_open_positions")
                        else []
                    )
                    seen: set = set()
                    for pos in open_positions:
                        sym = (
                            pos.get("symbol")
                            if isinstance(pos, dict)
                            else getattr(pos, "symbol", None)
                        )
                        if not sym or sym in seen:
                            continue
                        seen.add(sym)
                        try:
                            result = await self._market_price_fn(sym)
                        except Exception as exc:
                            logger.warning(
                                "[EODScheduler] price snapshot failed for %s: %s", sym, exc
                            )
                            snapshot[sym] = None
                            continue
                        if isinstance(result, dict):
                            price = (
                                result.get("last_price")
                                or result.get("price")
                                or result.get("last")
                                or result.get("close")
                            )
                        else:
                            price = result
                        try:
                            snapshot[sym] = float(price) if price not in (None, 0, 0.0) else None
                        except (TypeError, ValueError):
                            snapshot[sym] = None
                    resolved = sum(1 for v in snapshot.values() if v is not None)
                    logger.info(
                        "[EODScheduler] market-price snapshot built: %d/%d symbols resolved",
                        resolved,
                        len(snapshot),
                    )
                    flatten_kwargs["market_price_fn"] = snapshot.get
                else:
                    flatten_kwargs["market_price_fn"] = self._market_price_fn

            closed = self._tracker.flatten_all_positions(**flatten_kwargs)
            count = len(closed) if isinstance(closed, list) else 0
            net_pnl = sum(t.get("pnl", 0) for t in closed) if isinstance(closed, list) else 0.0
            logger.info(
                "[EODScheduler] Session flatten complete: closed %d positions, net P&L: $%.2f",
                count,
                net_pnl,
            )
        except Exception as exc:
            logger.exception("[EODScheduler] session_flatten failed: %s", exc)

    def register_with_scheduler(self, scheduler: Any) -> None:
        """
        Register EOD snapshot, weekly review, morning briefing, and VIX alert
        jobs with an APScheduler instance.

        Jobs
        ----
        * ``morning_briefing``  — Mon–Fri 8:25 AM CT (13:25 UTC)
        * ``eod_snapshot``      — Mon–Fri 3:05 PM CT (20:05 UTC)
        * ``weekly_review``     — Friday  3:30 PM CT (20:30 UTC)
        * ``vix_alert_check``   — Mon–Fri hourly 8 AM–5 PM CT
        * ``forward_test_snapshot`` — Mon–Fri 20:10 UTC (read-only)

        Parameters
        ----------
        scheduler:
            A configured ``apscheduler.schedulers.asyncio.AsyncIOScheduler``
            instance (already created in ``engine/main.py``).
        """
        from apscheduler.triggers.cron import CronTrigger

        # Morning briefing — Mon-Fri, 8:25 AM CT
        scheduler.add_job(
            self.run_morning_briefing,
            CronTrigger(
                day_of_week="mon-fri",
                hour=8,
                minute=25,
                timezone="America/Chicago",
            ),
            id="morning_briefing",
            name="Morning Briefing WhatsApp",
            max_instances=1,
            misfire_grace_time=300,  # 5-minute grace window
            replace_existing=True,
        )

        # EOD snapshot — Mon-Fri, 3:05 PM CT
        scheduler.add_job(
            self.run_eod_snapshot,
            CronTrigger(
                day_of_week="mon-fri",
                hour=20,
                minute=5,
                timezone="UTC",
            ),
            id="eod_snapshot",
            name="EOD P&L Snapshot",
            max_instances=1,
            misfire_grace_time=600,  # 10-minute grace window
            replace_existing=True,
        )

        # Weekly review — Friday, 3:30 PM CT
        scheduler.add_job(
            self.run_weekly_review,
            CronTrigger(
                day_of_week="fri",
                hour=20,
                minute=30,
                timezone="UTC",
            ),
            id="weekly_review",
            name="Weekly P&L Review",
            max_instances=1,
            misfire_grace_time=600,
            replace_existing=True,
        )

        # VIX alert check — Mon-Fri, every hour 8 AM–5 PM CT
        scheduler.add_job(
            self.run_vix_alert_check,
            CronTrigger(
                day_of_week="mon-fri",
                hour="8-17",
                minute=0,
                timezone="America/Chicago",
            ),
            id="vix_alert_check",
            name="VIX Threshold Alert",
            max_instances=1,
            misfire_grace_time=300,
            replace_existing=True,
        )

        # Session flatten: 3:45 PM ET = 20:45 UTC (Mon-Fri)
        scheduler.add_job(
            self.run_session_flatten,
            CronTrigger(day_of_week="mon-fri", hour=20, minute=45, timezone="UTC"),
            id="session_flatten",
            replace_existing=True,
        )
        logger.info("[EODScheduler] Session flatten job registered: Mon-Fri 20:45 UTC (3:45 PM ET)")

        # Forward-test snapshot — Mon-Fri 20:10 UTC, just after the EOD snapshot
        # so it scores the day's freshly-closed trades. Read-only.
        scheduler.add_job(
            self.run_forward_test_snapshot,
            CronTrigger(day_of_week="mon-fri", hour=20, minute=10, timezone="UTC"),
            id="forward_test_snapshot",
            name="Forward-Test Candidate Snapshot",
            max_instances=1,
            misfire_grace_time=600,
            replace_existing=True,
        )

        logger.info(
            "EODScheduler registered 6 APScheduler jobs: "
            "morning_briefing (Mon-Fri 08:25 CT) | "
            "eod_snapshot (Mon-Fri 20:05 UTC) | weekly_review (Fri 20:30 UTC) | "
            "vix_alert_check (Mon-Fri 08:00-17:00 CT hourly) | "
            "session_flatten (Mon-Fri 20:45 UTC) | "
            "forward_test_snapshot (Mon-Fri 20:10 UTC)"
        )

    # ── Private WhatsApp formatters ───────────────────────────────────────────

    async def _send_eod_whatsapp(self, snapshot: Dict[str, Any]) -> None:
        """Format and send the EOD summary via WhatsApp."""
        if not getattr(self._notifier, "enabled", False):
            return

        pnl_sign = "+" if snapshot["realized_pnl"] >= 0 else ""
        unreal_sign = "+" if snapshot["unrealized_pnl"] >= 0 else ""
        win_pct = (
            int(snapshot["winning_trades"] / snapshot["total_trades"] * 100)
            if snapshot["total_trades"] > 0
            else 0
        )

        lines = [
            "JARVIS EOD SNAPSHOT",
            f"Date:           {snapshot['date']}",
            f"Realized P&L:   {pnl_sign}{snapshot['realized_pnl']:.2f}",
            f"Unrealized P&L: {unreal_sign}{snapshot['unrealized_pnl']:.2f}",
            f"End Balance:    {snapshot['ending_balance']:.2f}",
            f"Trades:         {snapshot['total_trades']} ({win_pct}% win)",
            f"Max Drawdown:   {snapshot['max_drawdown']:.2f}",
        ]
        await self._notifier.send("\n".join(lines))

    async def _send_weekly_whatsapp(self, summary: Dict[str, Any]) -> None:
        """Format and send the weekly review via WhatsApp."""
        if not getattr(self._notifier, "enabled", False):
            return

        pnl_sign = "+" if summary["total_pnl"] >= 0 else ""
        pf_str = (
            f"{summary['profit_factor']:.2f}" if summary["profit_factor"] is not None else "N/A"
        )
        win_pct = int(summary["win_rate"] * 100)

        lines = [
            "JARVIS WEEKLY REVIEW",
            f"Week ending:    {summary['week_ending']}",
            f"Trading days:   {summary['trading_days']}",
            f"Total P&L:      {pnl_sign}{summary['total_pnl']:.2f}",
            f"Win rate:       {win_pct}%",
            f"Profit factor:  {pf_str}",
            f"Total trades:   {summary['total_trades']}",
            f"Max Drawdown:   {summary['max_drawdown']:.2f}",
        ]
        await self._notifier.send("\n".join(lines))
