"""
JARVIS TRADER — Paper Stop-Loss Monitor (Initiative 1, Track A2)
================================================================
An *independent*, in-process backstop for paper stop-loss enforcement.

Why this exists
---------------
Paper stops were enforced by exactly ONE mechanism: the standalone
``paper_runner`` bar-monitoring loop. That loop reads OHLC bars through the
historical-bar waterfall (TradingView MCP → IBKR → SQLite cache → Polygon →
CSV); when every source misses, the cycle silently no-ops on ``data_error``
and the open position is left UNMANAGED. On 2026-06-01 the IB Gateway was down
all day, the bar cache went stale, and MGC trade #178's stop (4497.51) was
never evaluated for ~13 h — the position bled to a session-flatten at 4375.5,
122 pts past the stop, for −$1,284 (−12.8% of the paper account). Root cause +
ranked fixes: ``docs/issues/ISSUE_2026-06-01_paper-stop-not-enforced-when-data-feed-down.md``.

This monitor closes that gap by decoupling stop enforcement from the
``paper_runner`` cron AND from the historical-bar waterfall:

  * It runs as an asyncio task inside the engine lifespan (registered in
    ``main.py`` ``_complete_background_init``), every ``interval_s`` seconds.
  * It loads open ``paper_trades`` straight from SQLite (Ledger A) and prices
    each via ``data_manager.get_current_price()`` — the TICK path (IBKR snapshot
    → Schwab → TradingView Tier-2.5 → Polygon stream), which is *independent of*
    the bar-fetch pipeline that proved it can vanish for hours.
  * On a breach it closes the trade through ``db.close_paper_trade()``, which is
    idempotent (``WHERE status='open'``) — so a race with the ``paper_runner``
    closing the same position is harmless: whoever wins, the loser's UPDATE
    matches zero rows and no-ops.

It is a *backstop*, not the primary path. It does not model slippage/commission
the way the runner does (it records the observed breach price); the goal is to
never again leave an open position unprotected, not to be the canonical fill.

Paper-only. Gated behind ``PAPER_STOP_MONITOR_ENABLED`` (default on).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("jarvis_trader.services.paper_stop_monitor")

# Contract point-values ($ per 1.00 price move per contract). Fallback only —
# the live value is read from paper_config.PAPER_CONFIGS[symbol]["multiplier"]
# when available; this map keeps the backstop functional even if that import
# fails (the monitor must never be the thing that can't load).
_FALLBACK_MULTIPLIERS: Dict[str, float] = {
    "MES": 5.0,
    "MNQ": 2.0,
    "MCL": 100.0,
    "MGC": 10.0,
    "ES": 50.0,
    "NQ": 20.0,
    "CL": 1000.0,
    "GC": 100.0,
}

_LONG_ALIASES = {"long", "buy", "b", "bull", "1"}
_SHORT_ALIASES = {"short", "sell", "s", "bear", "-1"}

# Stop enforcement must act ONLY on live tick data. get_current_price()'s waterfall
# can fall through to STALE fallback tiers — Polygon REST cache, the CSV daily-close
# (Tier 5), and an IBKR historical last-close — each tagged with a non-live `source`.
# Enforcing a stop against a day-old price is the #178 failure mode in reverse: on a
# dark feed the backstop would read a frozen price, see "no breach", and stay quiet
# (or fire at a mispriced level) — exactly the false-comfort this monitor exists to
# prevent. So any non-live source is treated as "can't act this tick" and we defer to
# the paper_runner A1 "feed dark" CRITICAL alert. These are the live tick tiers named
# in this module's docstring (IBKR snapshot → Schwab → TradingView 2.5 → Polygon stream).
_LIVE_PRICE_SOURCES = frozenset({"ibkr", "schwab", "tradingview", "polygon_stream"})


# ── Pure helpers (no engine deps — unit-tested in tests/test_paper_stop_monitor.py)

def normalize_side(side: Any) -> str:
    """Map any recorded side encoding to canonical 'long' / 'short'.

    Ledger-A rows have been seen with side='buy' (trade #178), while the runner's
    management code keys on side=='long'. A backstop must tolerate every encoding
    that has ever been written, so we normalize defensively. Unknown values pass
    through lower-cased (caller treats non-long/short as 'cannot evaluate').
    """
    s = str(side or "").strip().lower()
    if s in _LONG_ALIASES:
        return "long"
    if s in _SHORT_ALIASES:
        return "short"
    return s


def is_stop_breached(side: Any, stop: Optional[float], price: Optional[float]) -> bool:
    """True iff ``price`` has crossed the stop in the losing direction.

    Long  → breached when price <= stop.
    Short → breached when price >= stop.
    Missing stop or price → False (cannot evaluate, never fabricate a breach).
    """
    if stop is None or price is None:
        return False
    try:
        stop_f = float(stop)
        price_f = float(price)
    except (TypeError, ValueError):
        return False
    norm = normalize_side(side)
    if norm == "long":
        return price_f <= stop_f
    if norm == "short":
        return price_f >= stop_f
    return False


def compute_stop_pnl(
    side: Any,
    entry_price: float,
    exit_price: float,
    quantity: float,
    multiplier: float,
) -> float:
    """Realized PnL of closing at ``exit_price`` (no slippage/commission — backstop)."""
    norm = normalize_side(side)
    qty = abs(float(quantity or 0.0))
    delta = float(exit_price) - float(entry_price)
    if norm == "short":
        delta = -delta
    return round(delta * qty * float(multiplier), 2)


def multiplier_for(symbol: str, configs: Optional[Dict[str, Any]] = None) -> float:
    """Point-value for ``symbol``: paper_config first, then fallback map, then 1.0."""
    sym = str(symbol or "").upper()
    if configs:
        cfg = configs.get(sym) or {}
        m = cfg.get("multiplier")
        if m:
            try:
                return float(m)
            except (TypeError, ValueError):
                pass
    return _FALLBACK_MULTIPLIERS.get(sym, 1.0)


def _load_paper_configs() -> Optional[Dict[str, Any]]:
    """Best-effort import of PAPER_CONFIGS; None if unavailable (use fallbacks)."""
    try:
        from backtest.paper_config import PAPER_CONFIGS

        return PAPER_CONFIGS
    except Exception:  # noqa: BLE001
        return None


def _notify(message: str) -> None:
    """Send a WhatsApp alert if Twilio env vars are configured (graceful no-op)."""
    try:
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        from_num = os.environ.get("TWILIO_WHATSAPP_FROM", "")
        to_num = os.environ.get("WHATSAPP_TO", "")
        if not all([account_sid, auth_token, from_num, to_num]):
            return

        import httpx

        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        httpx.post(
            url,
            data={"From": from_num, "To": to_num, "Body": message},
            auth=(account_sid, auth_token),
            timeout=10.0,
        )
    except Exception:  # noqa: BLE001
        pass  # A monitor must never crash on a notification failure.


def _is_enabled() -> bool:
    return os.environ.get("PAPER_STOP_MONITOR_ENABLED", "true").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _interval_from_env(default: int = 60) -> int:
    raw = os.environ.get("PAPER_STOP_MONITOR_INTERVAL_S", "").strip()
    if not raw:
        return default
    try:
        val = int(float(raw))
        return val if val >= 5 else default
    except (TypeError, ValueError):
        return default


def _max_loss_usd_from_env(default: float = 750.0) -> float:
    """Hard per-trade catastrophe cap in USD (live unrealized loss).

    The breach path above only protects trades that *recorded* a stop_loss; a
    row with stop_loss NULL/0 is skipped entirely. That gap let two positions
    bleed out unmanaged: MGC #178 (2026-06-01, -$1,284, null-stop skip + dark
    feed) and the 2026-06-18 MES short (-$5,440, no stop, ran 1,088 pts to a
    session-flatten). This cap closes it — ANY open position whose live
    unrealized loss exceeds the cap is force-closed, stop or not. It is a
    last-resort catastrophe brake, sized well above normal trade losses (the
    fleet's typical loser is ~-$50), not a substitute for per-trade stops.

    Read live from env each sweep (matches PAPER_STOP_MONITOR_* convention).
    Set PAPER_MAX_LOSS_USD_PER_TRADE=0 to disable the backstop entirely.
    """
    raw = os.environ.get("PAPER_MAX_LOSS_USD_PER_TRADE", "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
        return val if val > 0 else 0.0
    except (TypeError, ValueError):
        return default


class PaperStopMonitor:
    """Feed-independent stop-loss backstop for open paper trades."""

    def __init__(
        self,
        db_manager,
        data_manager,
        interval_s: Optional[int] = None,
        oms_manager_getter: Optional[Any] = None,
    ):
        self.db = db_manager
        self.data = data_manager
        self.interval_s = interval_s if interval_s is not None else _interval_from_env()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Lazy getter (not a direct reference) because main.py constructs this
        # monitor from a background-init task that races the OMS v2 manager's
        # own construction -- see resolve_stop_for_symbol() below for why this
        # fallback exists at all. A plain `oms_manager=` kwarg could capture
        # None permanently if the race lands the wrong way; a zero-arg getter
        # re-reads the module global fresh on every sweep instead.
        self._oms_manager_getter = oms_manager_getter

    async def start(self) -> None:
        if not _is_enabled():
            logger.info(
                "🛡️ PaperStopMonitor disabled via PAPER_STOP_MONITOR_ENABLED — not starting"
            )
            return
        if self._running:
            return
        self._running = True
        logger.info(
            "🛡️ PaperStopMonitor: starting feed-independent stop backstop "
            f"(interval={self.interval_s}s)"
        )
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("🛑 PaperStopMonitor: stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.check_once()
            except asyncio.CancelledError:  # graceful shutdown
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[PaperStopMonitor] loop error: {exc}", exc_info=True)
            await asyncio.sleep(self.interval_s)

    def _resolve_oms_fallback_stop(self, symbol: Any) -> Optional[float]:
        """Best-effort OMS v2 stop lookup; None on any failure or absence.

        See ``OMSManager.resolve_stop_for_symbol`` for why this fallback
        exists: OMS-bracket-opened paper_trades rows can have ``stop_loss``
        NULL in the DB even though the OMS itself holds the real stop in
        memory. Must never raise -- a monitor sweep cannot fail because this
        best-effort extra lookup misbehaved.
        """
        if self._oms_manager_getter is None:
            return None
        try:
            oms = self._oms_manager_getter()
        except Exception:  # noqa: BLE001
            return None
        if oms is None or not hasattr(oms, "resolve_stop_for_symbol"):
            return None
        try:
            return oms.resolve_stop_for_symbol(symbol)
        except Exception:  # noqa: BLE001
            return None

    async def check_once(self) -> int:
        """One sweep over open paper trades. Returns the count of stops fired."""
        # DB calls are blocking SQLite — keep them off the event loop.
        open_trades = await asyncio.to_thread(self.db.get_open_trades)
        if not open_trades:
            return 0

        configs = _load_paper_configs()
        max_loss = _max_loss_usd_from_env()
        fired = 0

        for t in open_trades:
            stop = t.get("stop_loss")
            symbol = t.get("symbol")
            has_stop = stop not in (None, "", 0, 0.0)
            if not has_stop:
                # OMS v2 bracket-executed trades never persist stop_loss onto
                # the paper_trades row (PortfolioTracker.open_trade() has no
                # stop_loss parameter -- a separate, documented data-hygiene
                # gap, out of scope here). Fall back to the OMS's own
                # in-memory bracket record, which DOES hold the real
                # stop_loss_price from execute_bracket() time, before
                # deferring to the max-loss-only path below.
                _oms_stop = self._resolve_oms_fallback_stop(symbol)
                if _oms_stop is not None:
                    stop = _oms_stop
                    has_stop = True
            if not has_stop and max_loss <= 0:
                # No stop recorded (DB or OMS) and the catastrophe cap is
                # disabled → nothing to enforce. (With the cap on, a null-stop
                # row still falls through to the max-loss backstop below.)
                continue

            trade_id = t.get("trade_id")
            side = t.get("side")
            if not symbol or not trade_id:
                continue

            try:
                # Per-symbol asset class: equities (OPTIONS_WATCHLIST) must be
                # priced with is_futures=False or the quote/source is wrong.
                try:
                    from config import settings as _cfg_sm

                    _is_fut = str(symbol).upper() in {
                        str(x).upper() for x in (_cfg_sm.FUTURES_WATCHLIST or [])
                    }
                except Exception:
                    _is_fut = True
                quote = await self.data.get_current_price(symbol, is_futures=_is_fut)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[PaperStopMonitor] price fetch failed for {symbol}: {exc}")
                continue

            price = (quote or {}).get("last_price")
            if not price:
                # Genuinely unavailable — the paper_runner A1 guard owns the
                # "feed is dark" alerting; the monitor simply can't act this tick.
                continue

            source = (quote or {}).get("source")
            if source not in _LIVE_PRICE_SOURCES:
                # Stale-data guard: get_current_price fell through to a non-live
                # tier (csv_cache daily close, ibkr_historical, *_expired). Acting
                # on a frozen price would defeat the whole point of a feed-
                # independent backstop — defer to the A1 "feed dark" alert.
                logger.debug(
                    f"[PaperStopMonitor] {symbol}: skipping non-live price "
                    f"source {source!r} (stale-data guard)"
                )
                continue

            entry_price = t.get("entry_price") or 0.0
            quantity = t.get("quantity") or 1.0
            mult = multiplier_for(symbol, configs)
            pnl = compute_stop_pnl(side, entry_price, price, quantity, mult)

            stop_hit = has_stop and is_stop_breached(side, stop, price)
            # Catastrophe backstop: force-close ANY position (stop recorded or
            # not) once its live unrealized loss exceeds the hard cap. This is the
            # net that the null-stop skip above used to leave open.
            max_loss_hit = max_loss > 0 and pnl <= -max_loss
            if not stop_hit and not max_loss_hit:
                continue

            closed = await asyncio.to_thread(
                self.db.close_paper_trade, trade_id, float(price), None, pnl
            )
            if not closed:
                # Lost the race to the paper_runner (or already closed) — fine.
                logger.info(
                    f"[PaperStopMonitor] {symbol} close-signal but trade {str(trade_id)[:8]} "
                    "already closed (race with runner) — no-op"
                )
                continue

            fired += 1
            src = (quote or {}).get("source", "?")
            reason = "STOP FIRED" if stop_hit else "MAX-LOSS BACKSTOP"
            logger.critical(
                f"🛡️ [PaperStopMonitor] {reason} {symbol} "
                f"{normalize_side(side).upper()} qty={quantity} "
                f"entry={entry_price} stop={stop} fill={price} ({src}) pnl={pnl:+.2f}"
            )
            _notify(
                f"🛡️ JARVIS PAPER | {symbol} {reason}\n"
                f"{normalize_side(side).upper()} {quantity} @ {entry_price}\n"
                f"Stop {stop} | Fill {price} ({src})\n"
                f"PnL {pnl:+.2f}"
            )

        return fired
