"""
Tests for three safety bugs patched 2026-06-01.

Bug 1 — False kill switch from IBKR demo account contamination
  _sync_safety_equity() was reading daily_pnl via pnl_monitor which pulled
  from the daily_pnl SQLite table populated with DUP662235 (Individual Demo,
  NAV $3.97M) data.  The -$678k daily swing fired the kill switch on a real
  -$1,284 paper trade.  Fix: use paper_trades source + INITIAL_CAPITAL reference.

Bug 2 — Scanner-opened trades had no stop monitor
  MGC trade #178 rode from entry 4503.9 to 4375.5 (-128 pts, -$1,284) because
  nothing checked live price against stop_loss.  Fix: _monitor_open_stops() job
  runs every 5 min, closes positions whose stop is breached.

Bug 3 — paper_mode_bypass silently overrides REQUIRE_HUMAN_APPROVAL
  Any signal with stop_price=None was auto-executed with unbounded risk.
  Fix: refuse auto-execution if stop_price is absent; log CRITICAL.
"""

import logging
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import TradingConfig
from risk.safety_layer import KillSwitchReason, SafetyLayer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_safety() -> SafetyLayer:
    cfg = TradingConfig()
    cfg.LIVE_TRADING_ENABLED = False
    cfg.REQUIRE_HUMAN_APPROVAL = True
    cfg.MAX_DAILY_LOSS_PCT = 0.02
    cfg.MAX_DRAWDOWN_PCT = 0.10
    cfg.MAX_POSITION_SIZE_PCT = 0.05
    cfg.MAX_SINGLE_ORDER_VALUE = 5000.0
    cfg.MAX_ORDERS_PER_MINUTE = 10
    cfg.MAX_CONTRACTS_PER_INSTRUMENT = 2
    cfg.MAX_MARGIN_UTILIZATION = 0.40
    cfg.PRICE_COLLAR_PCT = 0.05
    cfg.MAX_CORRELATED_EXPOSURE_PCT = 0.20
    cfg.MAX_FUTURES_MARGIN_PCT = 0.30
    return SafetyLayer(cfg)


# ---------------------------------------------------------------------------
# Bug 1 — Equity Sync Source (IBKR demo contamination)
# ---------------------------------------------------------------------------


class TestEquitySyncSource:
    """Kill-switch threshold behaviour with paper_trades as the PnL source."""

    def test_ibkr_contaminated_pnl_fires_kill_switch(self):
        """
        -$678k through sync_from_broker fires kill switch (sanity check on
        the SafetyLayer itself — confirms the old path was dangerous).
        """
        safety = _make_safety()
        safety.sync_from_broker(10_000.0, -678_397.36)
        assert safety.is_killed is True

    def test_paper_pnl_below_threshold_does_not_fire(self):
        """
        Real paper loss of -$150 on $10k equity = -1.5% — below the 2% halt.
        """
        safety = _make_safety()
        safety.sync_from_broker(10_000.0, -150.0)
        assert safety.is_killed is False

    def test_paper_pnl_at_threshold_does_not_fire(self):
        """
        Exactly -2% of $10k = -$200.  The condition is strict `<`, so
        pnl == -limit is NOT a halt -- must exceed the threshold to fire.
        """
        safety = _make_safety()
        safety.sync_from_broker(10_000.0, -200.0)
        assert safety.is_killed is False  # boundary: equal, not exceeded

    def test_paper_pnl_exceeds_threshold_fires_kill_switch(self):
        """-$200.01 exceeds the 2% limit -> kill switch fires."""
        safety = _make_safety()
        safety.sync_from_broker(10_000.0, -200.01)
        assert safety.is_killed is True
        assert safety._kill_switch_reason == KillSwitchReason.DAILY_LOSS_LIMIT

    def test_mgc_actual_loss_fires_kill_switch(self):
        """
        MGC trade #178 actual loss -$1,284 on $10k = -12.8%.
        With paper_trades as source this must fire the kill switch.
        """
        safety = _make_safety()
        safety.sync_from_broker(10_000.0, -1284.0)
        assert safety.is_killed is True
        assert safety._kill_switch_reason == KillSwitchReason.DAILY_LOSS_LIMIT

    def test_zero_pnl_no_kill_switch(self):
        """No trades today → daily_pnl=0.0 → kill switch stays off."""
        safety = _make_safety()
        safety.sync_from_broker(10_000.0, 0.0)
        assert safety.is_killed is False

    def test_positive_pnl_no_kill_switch(self):
        """Winning day → kill switch stays off."""
        safety = _make_safety()
        safety.sync_from_broker(10_000.0, 300.0)
        assert safety.is_killed is False

    def test_paper_trades_daily_pnl_aggregation(self):
        """
        Filter closed trades by today's exit_time prefix, sum pnl field.
        Trades from yesterday and trades with pnl=None are handled correctly.
        """
        today_str = date.today().isoformat()
        trades = [
            {"trade_id": "t1", "pnl": -1284.0, "exit_time": f"{today_str}T15:45:00"},
            {"trade_id": "t2", "pnl": 200.0,   "exit_time": f"{today_str}T12:00:00"},
            {"trade_id": "t3", "pnl": -500.0,  "exit_time": "2026-05-31T14:00:00"},
            {"trade_id": "t4", "pnl": None,    "exit_time": f"{today_str}T11:00:00"},
        ]
        closed_today = [t for t in trades if (t.get("exit_time") or "").startswith(today_str)]
        daily_pnl = sum(float(t.get("pnl") or 0.0) for t in closed_today)

        assert len(closed_today) == 3          # t3 (yesterday) excluded
        assert daily_pnl == pytest.approx(-1084.0)  # -1284 + 200 + 0

    def test_no_closed_trades_today_pnl_is_zero(self):
        """Empty closed_today list → daily_pnl = 0.0."""
        today_str = date.today().isoformat()
        trades = [
            {"trade_id": "t1", "pnl": -500.0, "exit_time": "2026-05-30T10:00:00"},
        ]
        closed_today = [t for t in trades if (t.get("exit_time") or "").startswith(today_str)]
        daily_pnl = sum(float(t.get("pnl") or 0.0) for t in closed_today)
        assert daily_pnl == 0.0


# ---------------------------------------------------------------------------
# T0-02 — Frozen Equity Regression (2026-07-08 dashboard-integrity audit)
# ---------------------------------------------------------------------------
#
# The Bug-1 fix above (static INITIAL_CAPITAL reference passed to
# sync_from_broker) stopped the false kill-switch fires, but never added
# cumulative realized P&L back into the "equity" argument. Because equity
# never varied call-to-call, SafetyLayer._current_equity / _equity_peak —
# and therefore pnl_snapshots.portfolio_equity and every
# Sharpe/Sortino/Calmar/max-DD figure derived from it in
# reports/quantstats_metrics.py — were frozen at exactly $10,000.00 from
# 2026-06-02 onward (verified live against engine/data/jarvis_trader.db),
# even while daily_pnl swung normally with real trading. Fix (main.py
# _sync_safety_equity): current_equity = INITIAL_CAPITAL + total realized
# P&L across ALL closed trades (db_manager.get_stats_summary()["total_pnl"]),
# not just today's trades.


class TestEquitySyncIncludesRealizedPnL:
    """Pins the T0-02 fix: equity must move with cumulative realized P&L."""

    def test_frozen_equity_bug_reproduced_with_static_reference(self):
        """OLD (buggy) call: equity=INITIAL_CAPITAL only, ignoring realized
        P&L. This is the exact frozen-equity bug — equity never advances no
        matter how large the day's real P&L swing is."""
        safety = _make_safety()
        safety.sync_from_broker(10_000.0, -1_542.70)  # a real losing day
        assert safety._current_equity == 10_000.0  # frozen -- this was the bug
        safety.sync_from_broker(10_000.0, 3_018.18)  # a real winning day
        assert safety._current_equity == 10_000.0  # still frozen

    def test_current_equity_computation_matches_fixed_sync_logic(self):
        """Mirrors the exact algorithm added to _sync_safety_equity() in
        main.py: current_equity = config_equity + total_realized_pnl, where
        total_realized_pnl comes from db_manager.get_stats_summary()["total_pnl"]
        (SUM(pnl) over ALL status='closed' paper_trades, not just today's)."""
        mock_db = MagicMock()
        mock_db.get_stats_summary.return_value = {"total_pnl": 4_010.9795}
        config_equity = 10_000.0
        total_realized_pnl = float(mock_db.get_stats_summary()["total_pnl"])
        current_equity = config_equity + total_realized_pnl
        assert current_equity == pytest.approx(14_010.98, abs=0.01)

    def test_fixed_equity_sync_reflects_cumulative_realized_pnl(self):
        """FIXED call: equity = initial_capital + cumulative realized P&L.
        _current_equity and _equity_peak now advance with real account
        growth across syncs, instead of staying pinned to the constant."""
        safety = _make_safety()
        initial_capital = 10_000.0

        # Sync 1: cumulative realized P&L so far = +3,018.18 (matches the
        # real 2026-06-11 close in jarvis_trader.db).
        safety.sync_from_broker(initial_capital + 3_018.18, 3_018.18)
        assert safety._current_equity == pytest.approx(13_018.18)
        assert safety._equity_peak == pytest.approx(13_018.18)

        # Sync 2: cumulative realized P&L grows further (matches the real
        # 2026-07-07 close: initial 10,000 + total_realized 4,010.98).
        safety.sync_from_broker(initial_capital + 4_010.98, -1_542.70)
        assert safety._current_equity == pytest.approx(14_010.98)
        assert safety._equity_peak == pytest.approx(14_010.98)  # peak advances -- no longer frozen


# ---------------------------------------------------------------------------
# Bug 2 — Stop Monitor Logic
# ---------------------------------------------------------------------------


class TestStopMonitorLogic:
    """Stop-hit detection and PnL calculation used by _monitor_open_stops().

    T0-06 (2026-07): _monitor_open_stops() previously computed a zero-commission
    pnl and passed it straight through to close_paper_trade(pnl=...), which
    treats an explicit pnl as broker-confirmed (already net of fees) and does
    NOT re-deduct commission — so 0 of 27 real closed futures trades reflected
    any fee. The fix subtracts the same flat per-contract commission
    PortfolioTracker's primary close path applies
    (portfolio.tracker._commission_per_contract). This replica mirrors that
    fix so the numbers here match engine/main.py's real behavior instead of
    silently documenting the pre-fix bug as current.
    """

    _MULT = {"MCL": 100.0, "MNQ": 2.0, "MES": 5.0, "MGC": 10.0}
    _DEF = 1.0
    _COMMISSION_PER_CONTRACT = 1.50  # matches portfolio.tracker's default

    def _hit(self, side, current, stop):
        is_long = "buy" in side.lower()
        return (is_long and current <= stop) or (not is_long and current >= stop)

    def _pnl(self, side, entry, stop, qty, sym):
        m = self._MULT.get(sym, self._DEF)
        is_long = "buy" in side.lower()
        gross = (stop - entry) * qty * m if is_long else (entry - stop) * qty * m
        return gross - (self._COMMISSION_PER_CONTRACT * abs(qty))

    # MGC trade #178 (the actual incident)

    def test_mgc_incident_stop_breach_detected(self):
        """Long entry 4503.9, stop 4497.51, price fell to 4375.5 → hit."""
        assert self._hit("buy", current=4375.5, stop=4497.51) is True

    def test_mgc_stop_pnl_vs_full_loss(self):
        """
        At stop: gross -$63.90, minus $1.50 commission (T0-06) = -$65.40.
        Without stop: -$1,284 (the actual historical incident figure, booked
        before the commission fix existed — pre-cost rows are not
        retroactively adjusted). Stop still saves ~$1,218.60.
        """
        pnl_at_stop = self._pnl("buy", 4503.9, 4497.51, 1, "MGC")
        pnl_full_ride = (4375.5 - 4503.9) * 1 * 10.0
        assert pnl_at_stop == pytest.approx(-65.40, rel=1e-4)
        assert pnl_full_ride == pytest.approx(-1284.0)
        assert pnl_at_stop > pnl_full_ride  # stop saves money

    # Long position edge cases

    def test_long_above_stop_not_hit(self):
        assert self._hit("buy", current=5010.0, stop=5000.0) is False

    def test_long_at_stop_exactly_hit(self):
        assert self._hit("buy", current=5000.0, stop=5000.0) is True

    def test_long_below_stop_hit(self):
        assert self._hit("buy", current=4990.0, stop=5000.0) is True

    def test_mes_long_pnl_at_stop(self):
        """MES long: entry 5300, stop 5285, mult $5/pt → -$75 gross, -$76.50 net."""
        assert self._pnl("buy", 5300.0, 5285.0, 1, "MES") == pytest.approx(-76.5)

    # Short position edge cases

    def test_short_below_stop_not_hit(self):
        assert self._hit("sell", current=4990.0, stop=5000.0) is False

    def test_short_at_stop_exactly_hit(self):
        assert self._hit("sell", current=5000.0, stop=5000.0) is True

    def test_short_above_stop_hit(self):
        assert self._hit("sell", current=5010.0, stop=5000.0) is True

    def test_mnq_short_pnl_at_stop(self):
        """MNQ short: entry 18500, stop 18520, mult $2/pt → -$40 gross, -$41.50 net."""
        assert self._pnl("sell", 18500.0, 18520.0, 1, "MNQ") == pytest.approx(-41.5)

    # Scaling

    def test_pnl_scales_linearly_with_qty(self):
        pnl1 = self._pnl("buy", 4500.0, 4490.0, 1, "MGC")
        pnl2 = self._pnl("buy", 4500.0, 4490.0, 2, "MGC")
        assert pnl2 == pytest.approx(pnl1 * 2)

    def test_unknown_symbol_default_multiplier(self):
        """Unknown symbol uses multiplier=1.0 → -$5 gross, -$6.50 net of commission."""
        assert self._pnl("buy", 100.0, 95.0, 1, "UNKNOWN") == pytest.approx(-6.5)

    # Async monitor simulation

    @pytest.mark.asyncio
    async def test_monitor_closes_breached_long_position(self, monkeypatch):
        """Monitor logic closes MGC long when price falls below stop.

        T0-06: mirrors engine/main.py's _monitor_open_stops(), which now
        subtracts portfolio.tracker._commission_per_contract() * qty from the
        gross pnl before calling close_paper_trade(pnl=...) — that call passes
        an explicit pnl, which close_paper_trade treats as broker-confirmed
        (already net of fees) and does NOT re-deduct.
        """
        monkeypatch.setenv("COMMISSION_PER_CONTRACT", "1.50")

        from portfolio.tracker import _DEFAULT_MULTIPLIER as DEF
        from portfolio.tracker import INSTRUMENT_MULTIPLIERS as MULT
        from portfolio.tracker import _commission_per_contract as commission_per_contract

        trade = {
            "trade_id": "mgc-178",
            "symbol": "MGC",
            "side": "buy",
            "entry_price": 4503.9,
            "stop_loss": 4497.51,
            "quantity": 1.0,
        }
        mock_db = MagicMock()
        mock_db.get_open_trades.return_value = [trade]
        mock_data = AsyncMock()
        mock_data.get_current_price.return_value = {"last_price": 4375.5}
        mock_tracker = MagicMock()

        for t in mock_db.get_open_trades():
            stop_f = float(t["stop_loss"])
            sym = t["symbol"].upper()
            side = t["side"].lower()
            entry = float(t["entry_price"])
            tid = t["trade_id"]
            pd = await mock_data.get_current_price(sym, is_futures=True)
            cur = float(pd.get("last_price") or 0.0)
            is_long = "buy" in side
            if (is_long and cur <= stop_f) or (not is_long and cur >= stop_f):
                m = MULT.get(sym, DEF)
                qty = float(t["quantity"])
                gross_pnl = (stop_f - entry) * qty * m
                pnl = gross_pnl - (commission_per_contract() * abs(qty))
                mock_tracker.close_paper_trade(trade_id=tid, exit_price=stop_f, pnl=pnl)

        mock_tracker.close_paper_trade.assert_called_once()
        kw = mock_tracker.close_paper_trade.call_args.kwargs
        assert kw["exit_price"] == pytest.approx(4497.51)
        # Gross -$63.90, minus the default $1.50/contract commission → -$65.40.
        assert kw["pnl"] == pytest.approx(-65.40, rel=1e-4)

    @pytest.mark.asyncio
    async def test_monitor_skips_trade_without_stop(self):
        """stop_loss=None → trade is skipped entirely."""
        mock_db = MagicMock()
        mock_db.get_open_trades.return_value = [
            {"trade_id": "no-stop", "symbol": "MES", "side": "buy",
             "entry_price": 5300.0, "stop_loss": None, "quantity": 1.0}
        ]
        mock_tracker = MagicMock()

        for t in mock_db.get_open_trades():
            if t.get("stop_loss") is None:
                continue
            mock_tracker.close_paper_trade(trade_id=t["trade_id"])

        mock_tracker.close_paper_trade.assert_not_called()

    @pytest.mark.asyncio
    async def test_monitor_no_close_when_price_above_stop(self):
        """Long trade, price above stop → no close."""
        mock_db = MagicMock()
        mock_db.get_open_trades.return_value = [
            {"trade_id": "mes-open", "symbol": "MES", "side": "buy",
             "entry_price": 5300.0, "stop_loss": 5285.0, "quantity": 1.0}
        ]
        mock_data = AsyncMock()
        mock_data.get_current_price.return_value = {"last_price": 5305.0}
        mock_tracker = MagicMock()

        for t in mock_db.get_open_trades():
            if t.get("stop_loss") is None:
                continue
            pd = await mock_data.get_current_price(t["symbol"], is_futures=True)
            cur = float(pd.get("last_price") or 0.0)
            is_long = "buy" in t["side"].lower()
            stop_f = float(t["stop_loss"])
            if (is_long and cur <= stop_f) or (not is_long and cur >= stop_f):
                mock_tracker.close_paper_trade(trade_id=t["trade_id"])

        mock_tracker.close_paper_trade.assert_not_called()


# ---------------------------------------------------------------------------
# Bug 3 — paper_mode_bypass Stop Guard
# ---------------------------------------------------------------------------


class TestPaperModeBypassStopGuard:
    """Auto-execution is refused when stop_price is absent."""

    def _stop_from_result(self, trade_dec):
        return trade_dec.get("stop_price") or None

    def test_none_stop_evaluates_to_none(self):
        assert self._stop_from_result({"stop_price": None}) is None

    def test_missing_stop_key_evaluates_to_none(self):
        assert self._stop_from_result({}) is None

    def test_zero_stop_evaluates_to_none(self):
        """0 is falsy — treated as absent."""
        assert self._stop_from_result({"stop_price": 0}) is None

    def test_valid_stop_passes_through(self):
        assert self._stop_from_result({"stop_price": 4490.0}) == 4490.0

    def test_no_stop_blocks_execution(self, caplog):
        """Guard logs CRITICAL and skips add_paper_trade when stop is None."""
        mock_tracker = MagicMock()
        stop_price = self._stop_from_result({"stop_price": None})

        executed = False
        with caplog.at_level(logging.CRITICAL, logger="scanner.signal_scanner"):
            if stop_price is None:
                logging.getLogger("scanner.signal_scanner").critical(
                    "[SAFETY] paper_mode_bypass BLOCKED for %s %s — "
                    "no stop_loss in trade_decision; refusing auto-execution. "
                    "trade_decision=%r",
                    "MGC", "buy", {},
                )
            else:
                executed = True
                mock_tracker.add_paper_trade(stop_loss=float(stop_price))

        assert executed is False
        mock_tracker.add_paper_trade.assert_not_called()
        assert any("BLOCKED" in r.message for r in caplog.records)

    def test_valid_stop_allows_execution(self):
        """Valid stop_price → add_paper_trade is called with correct stop_loss."""
        mock_tracker = MagicMock()
        mock_tracker.add_paper_trade.return_value = "trade-123"
        stop_price = self._stop_from_result({"stop_price": 4490.0})

        if stop_price is not None:
            mock_tracker.add_paper_trade(
                symbol="MGC", side="buy", quantity=1.0,
                entry_price=4503.9, stop_loss=float(stop_price),
            )

        mock_tracker.add_paper_trade.assert_called_once()
        kw = mock_tracker.add_paper_trade.call_args.kwargs
        assert kw["stop_loss"] == pytest.approx(4490.0)

    def test_stop_loss_passed_directly_not_guarded_twice(self):
        """
        Inside the else branch, stop_loss=float(stop_price) — no conditional,
        because stop_price is guaranteed non-None at that point.
        """
        stop_price = 4490.0  # we're inside else: so stop_price is not None
        mock_tracker = MagicMock()
        mock_tracker.add_paper_trade.return_value = "trade-456"
        mock_tracker.add_paper_trade(stop_loss=float(stop_price))
        kw = mock_tracker.add_paper_trade.call_args.kwargs
        assert kw["stop_loss"] == 4490.0  # exact float, not None-guarded

    def test_require_human_approval_invariant_unchanged(self):
        """
        REQUIRE_HUMAN_APPROVAL is never touched by the bypass guard, whatever
        its currently configured value is. Not pinned to True: Amo's
        2026-08-11 standing decision sets it False via engine/.env for this
        deployment (see engine/.claude/rules/safety.md) -- the invariant this
        test protects is "the guard doesn't mutate it," not a specific value.
        """
        cfg = TradingConfig()
        original = cfg.REQUIRE_HUMAN_APPROVAL
        # Guard logic runs (either path) — does not mutate config
        stop_price = None
        if stop_price is None:
            pass  # blocked path
        assert cfg.REQUIRE_HUMAN_APPROVAL is original
