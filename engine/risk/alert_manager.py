"""
AlertManager — fires push alerts when trading thresholds are crossed.

Deduplicates alerts: each threshold fires at most once per trading day.
Provides an in-memory log of alerts sent today for the /safety/alerts/history endpoint.

Multi-channel fan-out (US-006)
-------------------------------
In addition to the primary ``notify_fn`` (OpenClaw / WhatsApp), AlertManager
now also dispatches to Telegram and Discord when those channels are configured.
Each channel is independently best-effort: a failure on one never blocks the
others.  Channels are enabled/disabled via environment variables read by the
existing notifier classes (``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_CHAT_ID`` for
Telegram; ``DISCORD_WEBHOOK_URL`` for Discord).  No tokens are read or echoed
here — the notifiers own their own config.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from risk.alert_thresholds import ALERT_THRESHOLDS

logger = logging.getLogger(__name__)

_CT = ZoneInfo("America/Chicago")

# Maximum alert history entries retained in memory
_MAX_HISTORY = 200


class AlertManager:
    """
    Monitors P&L state and fires push callbacks when thresholds are crossed.
    Thread-safe via asyncio event loop. Deduplicates within the same trading day.

    Usage
    -----
    alert_manager = AlertManager(notify_fn=whatsapp_notifier.send)
    alert_manager.start()                       # start background worker
    safety_layer.inject_alert_manager(alert_manager)

    # From safety layer after every sync:
    alert_manager.check_and_alert(
        daily_pnl=-150.0,
        daily_pnl_pct=-0.015,
        drawdown_pct=-0.06,
        consecutive_losses=3,
        portfolio_equity=10_000.0,
    )

    await alert_manager.stop()                  # on shutdown

    Multi-channel (US-006)
    ----------------------
    Telegram and Discord are automatically included when their respective env
    vars are set (``TELEGRAM_BOT_TOKEN``/``TELEGRAM_CHAT_ID`` and
    ``DISCORD_WEBHOOK_URL``).  Pass ``enable_telegram=False`` or
    ``enable_discord=False`` to suppress a channel regardless of env.
    """

    def __init__(
        self,
        notify_fn: Optional[Callable[[str], Awaitable[bool]]] = None,
        *,
        enable_telegram: bool = True,
        enable_discord: bool = True,
    ):
        """
        Parameters
        ----------
        notify_fn:
            Async callable that accepts a plain-text message string and sends it
            to the user (e.g. ``WhatsAppNotifier.send`` or
            ``openclaw_notifier.send_raw``).
        enable_telegram:
            When True (default), also deliver to Telegram if configured.
        enable_discord:
            When True (default), also deliver to Discord if configured.
        """
        self._notify = notify_fn
        self._enable_telegram = enable_telegram
        self._enable_discord = enable_discord

        # threshold_key → date it last fired (dedup guard)
        self._fired_today: dict[str, date] = {}

        # In-memory alert history: list of {"ts", "key", "message"} dicts
        # newest first — capped at _MAX_HISTORY entries
        self._history: list[dict] = []

        self._alert_queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task[None]] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the async alert worker task. Call once from lifespan startup."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._alert_worker())
            logger.info("[AlertManager] Worker task started")

    async def stop(self) -> None:
        """Gracefully stop the worker task. Call from lifespan shutdown."""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("[AlertManager] Worker task stopped")

    # ── Core check ────────────────────────────────────────────────────────

    def check_and_alert(
        self,
        daily_pnl: float,
        daily_pnl_pct: float,
        drawdown_pct: float,
        consecutive_losses: int,
        portfolio_equity: float,
    ) -> None:
        """
        Evaluate current P&L state against thresholds and queue any alerts.

        Non-blocking — queues alerts for async delivery by the worker task.
        Safe to call from sync or async contexts.

        Parameters
        ----------
        daily_pnl:
            Today's realized P&L in dollars (negative = loss).
        daily_pnl_pct:
            Today's P&L as fraction of portfolio equity (e.g. -0.015 = -1.5%).
        drawdown_pct:
            Current peak-to-trough drawdown as a negative fraction (e.g. -0.07 = -7%).
        consecutive_losses:
            Number of consecutive losing trades.
        portfolio_equity:
            Current account equity in dollars.
        """
        today = date.today()
        alerts: list[tuple[str, str]] = []  # (key, message)

        def _maybe(key: str, message: str) -> None:
            if self._fired_today.get(key) != today:
                self._fired_today[key] = today
                alerts.append((key, message))

        # ── Daily loss levels (mutually exclusive — only fire the worst) ──
        if daily_pnl_pct <= ALERT_THRESHOLDS["daily_loss_75pct"]:
            _maybe(
                "daily_loss_75pct",
                (
                    f"JARVIS ALERT | DAILY LOSS 75%\n"
                    f"P&L: ${daily_pnl:+.0f} ({daily_pnl_pct*100:.1f}%)\n"
                    f"Kill switch triggers at -2% — watch closely"
                ),
            )
        elif daily_pnl_pct <= ALERT_THRESHOLDS["daily_loss_50pct"]:
            _maybe(
                "daily_loss_50pct",
                (
                    f"JARVIS ALERT | DAILY LOSS 50%\n"
                    f"P&L: ${daily_pnl:+.0f} ({daily_pnl_pct*100:.1f}%)\n"
                    f"Halfway to daily limit — monitor closely"
                ),
            )
        elif daily_pnl_pct <= ALERT_THRESHOLDS["daily_loss_25pct"]:
            _maybe(
                "daily_loss_25pct",
                (
                    f"JARVIS ALERT | EARLY WARNING\n"
                    f"P&L: ${daily_pnl:+.0f} ({daily_pnl_pct*100:.1f}%)\n"
                    f"25% of daily limit consumed"
                ),
            )

        # ── Drawdown levels (mutually exclusive — only fire the worst) ────
        if drawdown_pct <= ALERT_THRESHOLDS["drawdown_10pct"]:
            _maybe(
                "drawdown_10pct",
                (
                    f"JARVIS ALERT | DRAWDOWN CRITICAL\n"
                    f"Drawdown: {drawdown_pct*100:.1f}%\n"
                    f"Kill switch imminent — equity=${portfolio_equity:,.0f}"
                ),
            )
        elif drawdown_pct <= ALERT_THRESHOLDS["drawdown_5pct"]:
            _maybe(
                "drawdown_5pct",
                (
                    f"JARVIS ALERT | DRAWDOWN WARNING\n"
                    f"Drawdown: {drawdown_pct*100:.1f}%\n"
                    f"Elevated risk — equity=${portfolio_equity:,.0f}"
                ),
            )

        # ── Consecutive loss levels (mutually exclusive) ──────────────────
        if consecutive_losses >= int(ALERT_THRESHOLDS["consecutive_losses_3"]):
            _maybe(
                "consecutive_losses_3",
                (
                    "JARVIS ALERT | 3 CONSECUTIVE LOSSES\n"
                    "Position scaling factor reduced\n"
                    "Review open positions — consider pausing"
                ),
            )
        elif consecutive_losses >= int(ALERT_THRESHOLDS["consecutive_losses_2"]):
            _maybe(
                "consecutive_losses_2",
                ("JARVIS ALERT | 2 CONSECUTIVE LOSSES\n" "Pattern forming — monitor closely"),
            )

        # ── Daily profit levels (mutually exclusive — only fire the best) ─
        if daily_pnl_pct >= ALERT_THRESHOLDS["daily_target_hit"]:
            _maybe(
                "daily_target_hit",
                (
                    f"JARVIS | DAILY TARGET HIT\n"
                    f"P&L: ${daily_pnl:+.0f} (+{daily_pnl_pct*100:.1f}%)\n"
                    f"Consider de-risking for remainder of session"
                ),
            )
        elif daily_pnl_pct >= ALERT_THRESHOLDS["daily_target_50pct"]:
            _maybe(
                "daily_target_50pct",
                (
                    f"JARVIS | HALFWAY TO TARGET\n"
                    f"P&L: ${daily_pnl:+.0f} (+{daily_pnl_pct*100:.1f}%)\n"
                    f"On track for daily goal"
                ),
            )

        for key, msg in alerts:
            self._alert_queue.put_nowait(msg)
            self._record_history(key, msg)

    # ── History ───────────────────────────────────────────────────────────

    def _record_history(self, key: str, message: str) -> None:
        """Store alert in in-memory history (newest first, capped at _MAX_HISTORY)."""
        entry = {
            "ts": datetime.now(_CT).isoformat(),
            "key": key,
            "message": message,
        }
        self._history.insert(0, entry)
        if len(self._history) > _MAX_HISTORY:
            self._history = self._history[:_MAX_HISTORY]

    def get_history(self, limit: int = 50) -> list[dict]:
        """Return the most recent alerts, newest first. Called by /safety/alerts/history."""
        # "Today" must be computed in the SAME zone the timestamps are stamped in
        # (_record_history uses datetime.now(_CT)). Using a naive date.today() here
        # silently dropped every alert whenever the host's local date ran ahead of
        # CT — e.g. a UTC host between 00:00–05:59 UTC (18:00–23:59 CT) saw an empty
        # history for ~6h nightly even though alerts had fired.
        today = datetime.now(_CT).date().isoformat()
        today_alerts = [h for h in self._history if h["ts"].startswith(today)]
        return today_alerts[:limit]

    def get_fired_keys(self) -> dict[str, str]:
        """Return {threshold_key: date_string} of thresholds fired today."""
        today = date.today()
        return {k: v.isoformat() for k, v in self._fired_today.items() if v == today}

    # ── Worker ────────────────────────────────────────────────────────────

    async def _deliver_telegram(self, message: str) -> None:
        """Best-effort Telegram delivery. Silently no-ops when not configured."""
        if not self._enable_telegram:
            return
        try:
            from notifications.telegram import get_notifier as _tg_notifier

            notifier = _tg_notifier()
            if not notifier.config_valid:
                return
            delivered = await notifier.send(message, parse_mode=None)
            if delivered:
                logger.info("[AlertManager/Telegram] Sent: %.80s", message.replace("\n", " | "))
            else:
                logger.warning("[AlertManager/Telegram] send returned falsy")
        except Exception as exc:
            logger.warning("[AlertManager/Telegram] delivery failed (non-fatal): %s", exc)

    async def _deliver_discord(self, message: str) -> None:
        """Best-effort Discord delivery. Silently no-ops when not configured."""
        if not self._enable_discord:
            return
        try:
            from notifications.discord_notifier import _send as _discord_send

            delivered = await _discord_send(message)
            if delivered:
                logger.info("[AlertManager/Discord] Sent: %.80s", message.replace("\n", " | "))
            else:
                logger.debug("[AlertManager/Discord] send returned falsy (not configured or disabled)")
        except Exception as exc:
            logger.warning("[AlertManager/Discord] delivery failed (non-fatal): %s", exc)

    async def _alert_worker(self) -> None:
        """Background task: drains the alert queue and delivers notifications."""
        while True:
            try:
                message = await self._alert_queue.get()

                # Primary channel (OpenClaw / WhatsApp)
                if self._notify:
                    try:
                        delivered = await self._notify(message)
                        if delivered:
                            logger.info("[AlertManager] Sent: %.80s", message.replace("\n", " | "))
                        else:
                            logger.warning(
                                "[AlertManager] notify_fn returned falsy — delivery failed: %.80s",
                                message.replace("\n", " | "),
                            )
                    except Exception as exc:
                        logger.error("[AlertManager] notify_fn raised: %s", exc)
                else:
                    logger.warning(
                        "[AlertManager] No notify_fn configured — primary alert dropped: %.80s",
                        message.replace("\n", " | "),
                    )

                # Fan-out: Telegram + Discord (independent best-effort)
                await asyncio.gather(
                    self._deliver_telegram(message),
                    self._deliver_discord(message),
                    return_exceptions=True,
                )

                self._alert_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[AlertManager] Worker error: %s", exc)
