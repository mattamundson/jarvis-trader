"""
JARVIS TRADER — End-of-Day Scheduler
Records daily P&L snapshots at market close and runs EOD analysis.

Schedule
--------
* EOD snapshot  : 3:05 PM CT (20:05 UTC) Mon–Fri — captures final daily P&L
* Weekly review : 3:30 PM CT (20:30 UTC) Friday  — 5-day rolling summary
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis_trader.eod_scheduler")

# Starting balance used when no prior DB record exists (paper trading default)
_DEFAULT_STARTING_BALANCE = 10_000.0


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
    ) -> None:
        self._db = db_manager
        self._tracker = portfolio_tracker
        self._notifier = whatsapp_notifier
        self._consolidator = learning_consolidator
        self._alert_manager = None  # Injected by main.py after ValidationAlertManager is created
        logger.info(
            "EODScheduler initialised — db=%s tracker=%s whatsapp=%s consolidator=%s",
            "yes" if self._db else "no",
            "yes" if self._tracker else "no",
            "yes" if self._notifier else "no",
            "yes" if self._consolidator else "no",
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

        starting_balance = self._get_starting_balance(today)
        metrics = self._collect_tracker_metrics(today)

        realized_pnl: float = metrics["realized_pnl"]
        unrealized_pnl: float = metrics["unrealized_pnl"]
        ending_balance = round(starting_balance + realized_pnl, 4)

        snapshot = {
            "date": today,
            "starting_balance": starting_balance,
            "ending_balance": ending_balance,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_trades": metrics["total_trades"],
            "winning_trades": metrics["winning_trades"],
            "losing_trades": metrics["losing_trades"],
            "max_drawdown": metrics["max_drawdown"],
        }

        # Persist to database
        if self._db is not None:
            try:
                self._db.upsert_daily_pnl(
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
                logger.info(
                    "[EOD] Snapshot saved — date=%s realized=%+.2f unrealized=%+.2f trades=%d",
                    today,
                    realized_pnl,
                    unrealized_pnl,
                    metrics["total_trades"],
                )
                snapshot["status"] = "ok"
            except Exception as exc:
                logger.error("[EOD] DB upsert failed: %s", exc)
                snapshot["status"] = "error"
                snapshot["error"] = str(exc)
        else:
            logger.warning("[EOD] No db_manager — snapshot not persisted")
            snapshot["status"] = "no_db"

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
        starting_balance = self._get_starting_balance(today)
        metrics = self._collect_tracker_metrics(today)

        realized_pnl: float = metrics["realized_pnl"]
        unrealized_pnl: float = metrics["unrealized_pnl"]
        ending_balance = round(starting_balance + realized_pnl, 4)

        return {
            "date": today,
            "starting_balance": starting_balance,
            "ending_balance": ending_balance,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": round(realized_pnl + unrealized_pnl, 4),
            "total_trades": metrics["total_trades"],
            "winning_trades": metrics["winning_trades"],
            "losing_trades": metrics["losing_trades"],
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

    async def run_session_flatten(self) -> None:
        """Flatten all open positions at end of session (3:45 PM ET = 20:45 UTC)."""
        logger.info("[EODScheduler] Session flatten triggered — closing all open positions")
        if self._tracker is None:
            logger.warning("[EODScheduler] session_flatten: no paper_tracker available")
            return

        try:
            # Call flatten_all_positions if available
            if hasattr(self._tracker, "flatten_all_positions"):
                closed = self._tracker.flatten_all_positions()
                count = len(closed) if isinstance(closed, list) else 0
                net_pnl = sum(t.get("pnl", 0) for t in closed) if isinstance(closed, list) else 0.0
                logger.info(
                    "[EODScheduler] Session flatten complete: closed %d positions, net P&L: $%.2f",
                    count,
                    net_pnl,
                )
            else:
                logger.warning("[EODScheduler] flatten_all_positions not available on tracker")
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

        logger.info(
            "EODScheduler registered 5 APScheduler jobs: "
            "morning_briefing (Mon-Fri 08:25 CT) | "
            "eod_snapshot (Mon-Fri 20:05 UTC) | weekly_review (Fri 20:30 UTC) | "
            "vix_alert_check (Mon-Fri 08:00-17:00 CT hourly) | "
            "session_flatten (Mon-Fri 20:45 UTC)"
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
