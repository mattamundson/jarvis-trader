"""
JARVIS TRADER — Real-time P&L Monitor
Reads actual account P&L from SQLite + IB Gateway to feed circuit breakers.

Source priority (highest to lowest):
  1. IB Gateway  — live broker data when connected (most accurate)
  2. SQLite       — persisted daily_pnl snapshots (survives restarts)
  3. In-memory    — PortfolioTracker paper-trade fallback (no persistence)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional, Tuple

logger = logging.getLogger("jarvis_trader.pnl_monitor")


# ── State container ────────────────────────────────────────────────────────────


@dataclass
class PnLState:
    """
    Snapshot of current P&L state as read from the best available source.

    All monetary values are in dollars (positive = profit, negative = loss).
    max_drawdown_pct is expressed as a negative percentage (e.g. -0.05 = -5%).
    """

    daily_realized_pnl: float = 0.0
    daily_unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    starting_balance: float = 0.0
    current_balance: float = 0.0
    max_drawdown_pct: float = 0.0  # negative or zero
    source: str = "memory"  # "ib" | "sqlite" | "memory"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    )


# ── Monitor ───────────────────────────────────────────────────────────────────


class PnLMonitor:
    """
    Reads account P&L from the best available source and exposes simple
    accessors that the SafetyLayer circuit breakers consume.

    Parameters
    ----------
    db_manager:
        DatabaseManager instance (schema.py).  Provides access to the
        ``daily_pnl`` table for persisted snapshots and peak-balance history.
    ib_gateway:
        IBKRExecutor (or any object with a coroutine ``get_account_summary()``
        that returns a dict with keys: total_equity, daily_pnl,
        unrealized_pnl).  May be None when IB is not connected.
    paper_tracker:
        PortfolioTracker instance.  Used as final fallback when neither IB
        nor SQLite have data for today.
    """

    def __init__(
        self,
        db_manager=None,
        ib_gateway=None,
        paper_tracker=None,
        starting_balance: float = 0.0,
    ) -> None:
        self._db = db_manager
        self._ib = ib_gateway
        self._paper = paper_tracker
        self._starting_balance = starting_balance  # configured paper balance fallback

        # Bug #2 fix: capture the tracker's total_pnl at session start so that
        # _read_memory() computes daily_realized = session_delta (not lifetime).
        # If the engine restarts daily the tracker starts at 0 and this is 0.
        # For multi-day sessions it captures yesterday's closing pnl as the
        # baseline, so only today's new trades count toward the daily limit.
        self._session_start_pnl: float = 0.0
        if paper_tracker is not None:
            try:
                perf = paper_tracker.get_performance()
                self._session_start_pnl = float(perf.get("total_pnl", 0.0) or 0.0)
            except Exception:
                pass

        # Cache the last successfully-read state so sync callers always get
        # something even if an async IB call hasn't completed yet.
        # Seed with configured starting_balance so health checks always see > 0.
        self._cached_state: PnLState = PnLState(
            starting_balance=starting_balance,
            current_balance=starting_balance,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def get_current_pnl_state(self) -> PnLState:
        """
        Return the best available PnLState.

        Source priority: IB Gateway → SQLite today row → in-memory tracker.

        Note: IB Gateway returns a coroutine; callers inside an async context
        should use ``await get_current_pnl_state_async()`` instead.  This
        synchronous version returns the most-recently-cached IB data (or falls
        through to SQLite / memory).
        """
        # Try SQLite today row first (synchronous, always available)
        sqlite_state = self._read_sqlite_today()
        if sqlite_state is not None:
            self._cached_state = sqlite_state
            return sqlite_state

        # Fall back to in-memory paper tracker
        memory_state = self._read_memory()
        if memory_state is not None:
            self._cached_state = memory_state
            return memory_state

        return self._cached_state

    async def get_current_pnl_state_async(self) -> PnLState:
        """
        Async version — tries IB Gateway first, then SQLite, then memory.
        Always returns a PnLState (never raises).
        """
        # 1. IB Gateway (most authoritative)
        ib_state = await self._read_ib_gateway()
        if ib_state is not None:
            self._cached_state = ib_state
            return ib_state

        # 2. SQLite persisted snapshot for today
        sqlite_state = self._read_sqlite_today()
        if sqlite_state is not None:
            self._cached_state = sqlite_state
            return sqlite_state

        # 3. In-memory paper tracker
        memory_state = self._read_memory()
        if memory_state is not None:
            self._cached_state = memory_state
            return memory_state

        logger.warning("[PnLMonitor] No P&L data source available — returning zero state")
        return PnLState()

    def get_daily_pnl(self) -> float:
        """
        Today's combined realized + unrealized P&L in dollars.
        Reads from best available synchronous source (IB cache or SQLite).
        """
        state = self.get_current_pnl_state()
        return state.daily_realized_pnl + state.daily_unrealized_pnl

    def get_drawdown_pct(self) -> float:
        """
        Current drawdown as a negative percentage from the all-time equity peak.
        Returns 0.0 if no peak data is available (no history).

        Example: -0.08 means the account is 8% below its peak.
        """
        state = self.get_current_pnl_state()
        current = state.current_balance
        if current <= 0:
            return 0.0

        # When the current state comes from the in-memory paper tracker and a
        # tracker is wired, use the tracker's own equity curve peak.  This avoids
        # false drawdown alarms where the DB's daily_pnl history (accumulated across
        # engine restarts with compounded paper balances) is many multiples larger
        # than the tracker's current session balance.
        if state.source == "memory" and self._paper is not None:
            try:
                perf = self._paper.get_performance()
                curve = perf.get("equity_curve", [])
                peak = max((float(v) for v in curve if v is not None), default=0.0)
                if peak > 0:
                    return (current - peak) / peak
            except Exception:
                pass
            return 0.0

        peak = self.get_peak_balance()
        if peak <= 0:
            return 0.0

        drawdown = (current - peak) / peak  # negative when current < peak
        return drawdown

    def should_halt_trading(
        self,
        daily_loss_limit_pct: float = -0.02,
        drawdown_limit_pct: float = -0.10,
    ) -> Tuple[bool, str]:
        """
        Check whether either circuit breaker has tripped.

        Parameters
        ----------
        daily_loss_limit_pct:
            Maximum acceptable daily loss as a fraction of starting balance.
            Must be negative (e.g. -0.02 = allow up to -2% daily loss).
        drawdown_limit_pct:
            Maximum acceptable drawdown from peak equity.
            Must be negative (e.g. -0.10 = allow up to -10% drawdown).

        Returns
        -------
        (should_halt, reason)
            should_halt: True  → at least one circuit breaker has tripped
            reason:      Human-readable explanation of which limit was hit,
                         or empty string when all clear.
        """
        state = self.get_current_pnl_state()
        daily_pnl = state.daily_realized_pnl + state.daily_unrealized_pnl

        # Daily loss check
        if state.starting_balance > 0:
            daily_pnl_pct = daily_pnl / state.starting_balance
        else:
            # No starting balance available; compare raw P&L to limit expressed
            # as a dollar threshold using the current balance as reference.
            reference = state.current_balance if state.current_balance > 0 else 1.0
            daily_pnl_pct = daily_pnl / reference

        if daily_pnl_pct < daily_loss_limit_pct:
            reason = (
                f"Daily loss limit breached: {daily_pnl_pct:.2%} < "
                f"{daily_loss_limit_pct:.2%} "
                f"(source={state.source})"
            )
            logger.warning(f"[PnLMonitor] CIRCUIT BREAKER — {reason}")
            return True, reason

        # Drawdown check
        drawdown = self.get_drawdown_pct()
        if drawdown < drawdown_limit_pct:
            reason = (
                f"Max drawdown breached: {drawdown:.2%} < "
                f"{drawdown_limit_pct:.2%} "
                f"(source={state.source})"
            )
            logger.warning(f"[PnLMonitor] CIRCUIT BREAKER — {reason}")
            return True, reason

        return False, ""

    def record_eod_snapshot(self) -> bool:
        """
        Write today's P&L snapshot to the SQLite daily_pnl table.

        Pulls data from the best available source (IB cache first, then
        in-memory paper tracker).  Should be called at market close (4pm ET).

        Returns True on success, False if no data is available or the DB
        write fails.
        """
        if self._db is None:
            logger.warning("[PnLMonitor] record_eod_snapshot: no db_manager available")
            return False

        state = self._cached_state
        if self._paper is not None and (state.source in ("memory", "ib")):
            # Always prefer paper tracker for EOD snapshots — prevents IB demo
            # account NAV from contaminating daily_pnl peak balance calculations.
            memory_state = self._read_memory()
            if memory_state:
                state = memory_state

        today = date.today().isoformat()

        # Gather trade counts from paper tracker if available
        total_trades = 0
        winning_trades = 0
        losing_trades = 0
        if self._paper is not None:
            try:
                perf = self._paper.get_performance()
                total_trades = perf.get("total_trades", 0)
                winning_trades = perf.get("winning_trades", 0)
                losing_trades = perf.get("losing_trades", 0)
            except Exception as exc:
                logger.warning(f"[PnLMonitor] Could not read paper tracker perf: {exc}")

        # Drawdown for the day (as a positive fraction, matching DB schema convention)
        drawdown_abs = abs(self.get_drawdown_pct())

        try:
            self._db.upsert_daily_pnl(
                date=today,
                starting_balance=state.starting_balance,
                ending_balance=state.current_balance,
                realized_pnl=state.daily_realized_pnl,
                unrealized_pnl=state.daily_unrealized_pnl,
                total_trades=total_trades,
                winning_trades=winning_trades,
                losing_trades=losing_trades,
                max_drawdown=drawdown_abs,
            )
            logger.info(
                f"[PnLMonitor] EOD snapshot written: date={today} "
                f"realized={state.daily_realized_pnl:+.2f} "
                f"unrealized={state.daily_unrealized_pnl:+.2f} "
                f"balance={state.current_balance:.2f}"
            )
            return True
        except Exception as exc:
            logger.error(f"[PnLMonitor] record_eod_snapshot DB write failed: {exc}")
            return False

    # A paper account 5x-ing its starting capital during forward validation is
    # already wildly implausible; a demo / IB-contaminated daily_pnl row (e.g. a
    # $3.97M IB NAV against a $10k paper book — ~400x) is far beyond that. The
    # daily_pnl table carries no source column, so we cannot filter by source on
    # the read path — instead we exclude rows whose ending_balance exceeds this
    # plausibility ceiling. This stops a single contaminated row from re-inflating
    # the equity peak and falsely tripping (or, inverted, masking) the max-drawdown
    # kill switch. Excluding a row biases the peak DOWN (smaller drawdown), the
    # fail-safe direction; 5x ($50k on a $10k book) is the tightest multiple that
    # leaves no false-positive risk for a real forward-validation run.
    PLAUSIBLE_PEAK_MULTIPLE = 5.0

    # The plausibility ceiling above stops an implausibly-LARGE row from inflating
    # the peak, but a *plausible-but-stale* high row (e.g. an $11.5k peak from
    # months ago on an $11k book) would still mask a genuine current drawdown and
    # under-fire the breaker. Bound the high-water mark to a trailing window so only
    # recent history can set the peak. 90d comfortably covers an active forward test
    # while discarding ancient snapshots. Reuses the DB layer's existing `days=`
    # cutoff (get_daily_pnl), so no date parsing lives here.
    PEAK_LOOKBACK_DAYS = 90

    def _plausible_peak_ceiling(self) -> float:
        """Upper bound on a believable paper equity peak, or 0.0 if no anchor."""
        if self._starting_balance and self._starting_balance > 0:
            return self._starting_balance * self.PLAUSIBLE_PEAK_MULTIPLE
        return 0.0

    def get_peak_balance(self) -> float:
        """
        Return the highest account balance recorded in the SQLite daily_pnl
        history.  Falls back to the in-memory paper tracker equity peak if the
        DB has no rows, or to zero if neither is available.

        Two guards keep a bad row from masking a real drawdown: rows older than
        ``PEAK_LOOKBACK_DAYS`` are excluded (a stale high row can't set the peak),
        and rows whose ending_balance exceeds the plausibility ceiling (see
        ``PLAUSIBLE_PEAK_MULTIPLE``) are treated as demo/IB contamination and
        excluded so they cannot inflate the peak used by the drawdown breaker.
        """
        # Try SQLite history first
        if self._db is not None:
            try:
                # Trailing-window high-water mark: only recent rows may set the
                # peak. Falls back to the unbounded read if this DB impl predates
                # the days= cutoff.
                try:
                    rows = self._db.get_daily_pnl(days=self.PEAK_LOOKBACK_DAYS)
                except TypeError:
                    rows = self._db.get_daily_pnl()
                if rows:
                    balances = [r.get("ending_balance", 0.0) or 0.0 for r in rows]
                    ceiling = self._plausible_peak_ceiling()
                    if ceiling > 0:
                        plausible = [b for b in balances if b <= ceiling]
                        dropped = len(balances) - len(plausible)
                        if dropped:
                            logger.warning(
                                "[PnLMonitor] get_peak_balance excluded %d implausible "
                                "daily_pnl row(s) above ceiling %.2f "
                                "(demo/IB contamination guard)",
                                dropped,
                                ceiling,
                            )
                        balances = plausible
                    peak = max(balances, default=0.0)
                    if peak > 0:
                        return peak
            except Exception as exc:
                logger.warning(f"[PnLMonitor] get_peak_balance DB read failed: {exc}")

        # Fall back to in-memory tracker's equity peak
        if self._paper is not None:
            try:
                perf = self._paper.get_performance()
                # get_performance() returns an equity_curve list; derive peak from it
                curve = perf.get("equity_curve", [])
                if curve:
                    return max(float(v) for v in curve if v is not None)
            except Exception as exc:
                logger.warning(f"[PnLMonitor] get_peak_balance tracker read failed: {exc}")

        return 0.0

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _read_ib_gateway(self) -> Optional[PnLState]:
        """
        Attempt to read live account summary from IB Gateway.
        Returns None if IB is not connected or the call fails.
        """
        if self._ib is None:
            return None

        try:
            # IBKRExecutor.get_account_summary() is a coroutine
            summary = await self._ib.get_account_summary()
            if not summary:
                return None

            total_equity = float(summary.get("total_equity", 0.0))
            daily_pnl = float(summary.get("daily_pnl", 0.0))
            unrealized_pnl = float(summary.get("unrealized_pnl", 0.0))

            # IB DailyPnL already includes both realized and unrealized intraday
            # so we split conservatively: realized = daily_pnl - unrealized
            realized_pnl = daily_pnl - unrealized_pnl

            # Derive starting balance: current equity minus daily movement
            starting_balance = total_equity - daily_pnl if total_equity > 0 else 0.0

            state = PnLState(
                daily_realized_pnl=realized_pnl,
                daily_unrealized_pnl=unrealized_pnl,
                total_pnl=daily_pnl,
                starting_balance=starting_balance,
                current_balance=total_equity,
                max_drawdown_pct=0.0,  # computed separately via get_drawdown_pct()
                source="ib",
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            )
            logger.debug(
                f"[PnLMonitor] IB Gateway state: equity={total_equity:.2f} "
                f"daily_pnl={daily_pnl:+.2f} unrealized={unrealized_pnl:+.2f}"
            )
            return state

        except Exception as exc:
            logger.warning(f"[PnLMonitor] IB Gateway read failed: {exc}")
            return None

    def _read_sqlite_today(self) -> Optional[PnLState]:
        """
        Read today's row from the daily_pnl SQLite table.
        Returns None if no row exists for today or the DB is unavailable.
        """
        if self._db is None:
            return None

        today_str = date.today().isoformat()
        try:
            rows = self._db.get_daily_pnl(start_date=today_str, end_date=today_str)
            if not rows:
                return None

            row = rows[0]
            starting = float(row.get("starting_balance", 0.0) or 0.0)
            # Fall back to configured starting balance when DB row has 0.0
            if starting <= 0 and self._starting_balance > 0:
                starting = self._starting_balance
            ending = float(row.get("ending_balance", 0.0) or 0.0)
            realized = float(row.get("realized_pnl", 0.0) or 0.0)
            unrealized = float(row.get("unrealized_pnl", 0.0) or 0.0)
            max_dd = float(row.get("max_drawdown", 0.0) or 0.0)

            state = PnLState(
                daily_realized_pnl=realized,
                daily_unrealized_pnl=unrealized,
                total_pnl=realized + unrealized,
                starting_balance=starting,
                current_balance=ending if ending > 0 else starting,
                max_drawdown_pct=-max_dd,  # stored as positive in DB; expose as negative
                source="sqlite",
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            )
            logger.debug(
                f"[PnLMonitor] SQLite today state: starting={starting:.2f} "
                f"ending={ending:.2f} realized={realized:+.2f} unrealized={unrealized:+.2f}"
            )
            return state

        except Exception as exc:
            logger.warning(f"[PnLMonitor] SQLite today read failed: {exc}")
            return None

    def _read_memory(self) -> Optional[PnLState]:
        """
        Read P&L from the in-memory PortfolioTracker.
        Returns None if the tracker is unavailable or has no trades.
        """
        if self._paper is None:
            return None

        try:
            perf = self._paper.get_performance()
            total_pnl = float(perf.get("total_pnl", 0.0) or 0.0)
            # Bug #2 fix: compute daily_realized as the delta since session start,
            # not the lifetime cumulative.  For daily-restart engines session_start_pnl
            # is 0 and daily_realized == total_pnl (no change in behaviour).  For
            # engines that run across day boundaries, only trades opened THIS session
            # count toward the daily loss limit, preventing stale losses from blocking
            # new sessions or inflating the equity peak used by the drawdown halt.
            daily_realized = total_pnl - self._session_start_pnl
            starting = float(perf.get("starting_balance", 0.0) or 0.0)
            # Fall back to configured starting balance when tracker has no history
            if starting <= 0 and self._starting_balance > 0:
                starting = self._starting_balance
            current = starting + total_pnl if starting > 0 else total_pnl

            # Equity curve to find peak
            curve = perf.get("equity_curve", [])
            peak = max((float(v) for v in curve if v is not None), default=0.0)
            dd_pct = ((current - peak) / peak) if peak > 0 else 0.0

            state = PnLState(
                daily_realized_pnl=daily_realized,
                daily_unrealized_pnl=0.0,
                total_pnl=total_pnl,
                starting_balance=starting,
                current_balance=current,
                max_drawdown_pct=dd_pct,
                source="memory",
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            )
            logger.debug(
                f"[PnLMonitor] Memory state: total_pnl={total_pnl:+.2f} "
                f"current={current:.2f} peak={peak:.2f}"
            )
            return state

        except Exception as exc:
            logger.warning(f"[PnLMonitor] Memory read failed: {exc}")
            return None
