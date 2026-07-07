"""
Supplemental coverage tests — push risk/ package from ~94% to >=95%.

Targets:
- safety_layer.py: TP child live path (1499-1517), sidecar bump (1542-1543/1550-1551),
  get_recommended_size import-fallback (1850-1855), _log_safety_event DB success
  path (1950-1952), flatten place_paper_order returns None (1610)
- alert_manager.py: daily_target_50pct branch (204), worker no-notify-fn else branch
  (261-264), worker outer exception handler (268-269), stop() cancel await (87-88)
- loss_tracker.py: _load_state corrupt-file path (116-118), _save_state failure
  (127-128), get_position_size_multiplier quarter_threshold (236), is_halted
  expired-halt auto-clear (267-270)
- margin_monitor.py: run_loop background iteration (134-139)
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from risk.alert_manager import AlertManager
from risk.loss_tracker import ConsecutiveLossTracker
from risk.margin_monitor import MarginMonitorAgent
from risk.safety_layer import SafetyLayer

# ── Helpers ───────────────────────────────────────────────────────────────────


def _live_settings(base):
    base.LIVE_TRADING_ENABLED = True
    base.REQUIRE_HUMAN_APPROVAL = False
    base.MAX_DAILY_LOSS_PCT = 0.99
    base.MAX_DRAWDOWN_PCT = 0.99
    base.MAX_POSITION_SIZE_PCT = 0.99
    base.MAX_SINGLE_ORDER_VALUE = 9_999_999.0
    base.MAX_ORDERS_PER_MINUTE = 10_000
    base.MAX_CONTRACTS_PER_INSTRUMENT = 100
    base.MAX_FUTURES_MARGIN_PCT = 0.99
    base.MAX_MARGIN_UTILIZATION = 0.99
    base.MAX_DAILY_LOSS_USD = 999_999.0
    base.MAX_TRADE_LOSS_USD = 999_999.0
    base.ALLOW_PAPER_SIMULATED_ORDERS = False
    return base


def _make_tracker(**kwargs) -> ConsecutiveLossTracker:
    tmpdir = tempfile.mkdtemp()
    defaults = {
        "data_dir": tmpdir,
        "consecutive_loss_half_size": 3,
        "consecutive_loss_quarter_size": 5,
        "consecutive_loss_halt": 7,
        "consecutive_loss_halt_hours": 24,
    }
    defaults.update(kwargs)
    return ConsecutiveLossTracker(**defaults)


# ── safety_layer -- TP child live path ────────────────────────────────────────
#
# submit_entry_with_stop checks the MODULE-LEVEL settings singleton at line 1490:
#   _live_trading = bool(getattr(settings, "LIVE_TRADING_ENABLED", False))
# NOT self._config.  Patch "risk.safety_layer.settings" to enable the TP branch.
#
# Call ordering when stop_price AND ib.is_connected():
#   call 1 -- submit_paper_order -> entry order (place_paper_order)
#   call 2 -- submit_paper_order -> linked stop (HB-1, place_paper_order)
#   call 3 -- submit_entry_with_stop -> direct STP child (place_paper_order)
#   call 4 -- submit_entry_with_stop -> TP child (place_paper_order, only if _live_trading)


@pytest.mark.asyncio
class TestSubmitEntryWithStopTpLive:
    async def test_tp_child_placed_when_live_trading_enabled(self, mock_settings):
        """target_price with patched module settings.LIVE_TRADING_ENABLED=True -> TP placed."""
        settings_obj = _live_settings(mock_settings)
        sl = SafetyLayer(settings_obj)
        sl._current_equity = 10_000.0

        call_count = {"n": 0}

        async def _place(**kwargs):
            call_count["n"] += 1
            return f"order-{call_count['n']}"

        ib = MagicMock()
        ib.is_connected.return_value = True
        ib.place_paper_order = AsyncMock(side_effect=_place)
        ib.get_order_status = AsyncMock(return_value={"parent_order_id": "order-1"})
        sl._ib_gateway = ib

        mock_module_settings = MagicMock()
        mock_module_settings.LIVE_TRADING_ENABLED = True

        with patch("risk.safety_layer.settings", mock_module_settings):
            result = await sl.submit_entry_with_stop(
                symbol="MES",
                action="BUY",
                quantity=1,
                price=5800.0,
                stop_price=5780.0,
                target_price=5840.0,
            )

        # 4 place_paper_order calls: entry, linked-stop, direct-STP, TP
        assert call_count["n"] >= 3
        assert result["approved"] is True
        assert result.get("tp_order_id") is not None

    async def test_tp_child_exception_sets_tp_id_none(self, mock_settings):
        """TP placement raises at call 4 -> tp_id=None but bracket still approved."""
        settings_obj = _live_settings(mock_settings)
        sl = SafetyLayer(settings_obj)
        sl._current_equity = 10_000.0

        call_count = {"n": 0}

        async def _place(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 4:
                raise RuntimeError("TP placement error")
            return f"order-{call_count['n']}"

        ib = MagicMock()
        ib.is_connected.return_value = True
        ib.place_paper_order = AsyncMock(side_effect=_place)
        ib.get_order_status = AsyncMock(return_value={"parent_order_id": "order-1"})
        sl._ib_gateway = ib

        mock_module_settings = MagicMock()
        mock_module_settings.LIVE_TRADING_ENABLED = True

        with patch("risk.safety_layer.settings", mock_module_settings):
            result = await sl.submit_entry_with_stop(
                symbol="MES",
                action="BUY",
                quantity=1,
                price=5800.0,
                stop_price=5780.0,
                target_price=5840.0,
            )

        # TP raised -> tp_id=None, but entry+STP already placed -> approved=True
        assert result["approved"] is True
        assert result.get("tp_order_id") is None


# ── safety_layer -- sidecar counter bump ──────────────────────────────────────


@pytest.mark.asyncio
class TestSidecarBump:
    async def test_sidecar_written_when_stp_succeeds(self, mock_settings):
        """Happy-path bracket order exercises the sidecar bump block (1529-1551)."""
        settings_obj = _live_settings(mock_settings)
        sl = SafetyLayer(settings_obj)
        sl._current_equity = 10_000.0

        call_count = {"n": 0}

        async def _place(**kwargs):
            call_count["n"] += 1
            return f"order-{call_count['n']}"

        ib = MagicMock()
        ib.is_connected.return_value = True
        ib.place_paper_order = AsyncMock(side_effect=_place)
        ib.get_order_status = AsyncMock(return_value={"parent_order_id": "order-1"})
        sl._ib_gateway = ib

        result = await sl.submit_entry_with_stop(
            symbol="MES",
            action="BUY",
            quantity=1,
            price=5800.0,
            stop_price=5780.0,
        )

        assert result["approved"] is True
        assert result["stp_order_id"] is not None


# ── safety_layer -- get_recommended_size import fallback ──────────────────────


class TestGetRecommendedSizeImportFallback:
    def test_both_imports_fail_returns_error_dict(self, mock_settings):
        """Both position_sizer imports fail -> error dict with recommended_contracts=0."""
        sl = SafetyLayer(mock_settings)
        sl._current_equity = 10_000.0

        import builtins

        original_import = builtins.__import__

        def _broken_import(name, *args, **kwargs):
            if "position_sizer" in name:
                raise ImportError(f"mocked import failure: {name}")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_broken_import):
            result = sl.get_recommended_size(
                symbol="MES",
                atr=5.0,
                account_value=10_000.0,
                current_drawdown=0.0,
            )

        assert "error" in result
        assert result["recommended_contracts"] == 0


# ── safety_layer -- _log_safety_event DB success path ─────────────────────────


@pytest.mark.asyncio
class TestLogSafetyEventDbSuccess:
    async def test_log_event_with_mock_repository_succeeds(self, mock_safety_layer):
        """_log_safety_event succeeds when repository.insert_safety_event is available."""
        sl = mock_safety_layer
        mock_repo = MagicMock()
        mock_repo.insert_safety_event = AsyncMock(return_value=None)

        with patch.dict("sys.modules", {"database": MagicMock(repository=mock_repo)}):
            await sl._log_safety_event(
                event_type="kill_switch_activate",
                reason="test_coverage",
                details={"resolved": True},
            )

        mock_repo.insert_safety_event.assert_called_once()

    async def test_log_event_details_none_resolved_defaults_false(self, mock_safety_layer):
        """When details=None, resolved defaults to False."""
        sl = mock_safety_layer
        mock_repo = MagicMock()
        mock_repo.insert_safety_event = AsyncMock(return_value=None)

        with patch.dict("sys.modules", {"database": MagicMock(repository=mock_repo)}):
            await sl._log_safety_event(
                event_type="daily_loss_halt",
                reason="daily_loss",
                details=None,
            )

        call_kwargs = mock_repo.insert_safety_event.call_args[1]
        assert call_kwargs.get("resolved") is False


# ── safety_layer -- flatten_all_positions returns None ────────────────────────


@pytest.mark.asyncio
class TestFlattenPlaceNone:
    async def test_place_paper_order_returns_none_adds_error(self, mock_safety_layer):
        """place_paper_order returns None (not exception) -> error dict added."""
        sl = mock_safety_layer
        ib = MagicMock()
        ib.get_positions = AsyncMock(return_value=[{"symbol": "MES", "position": 1}])
        ib.place_paper_order = AsyncMock(return_value=None)
        sl._ib_gateway = ib

        result = await sl.flatten_all_positions()
        assert result["flattened"] == []
        assert len(result["errors"]) == 1
        assert "None" in result["errors"][0]["error"]


# ── alert_manager -- daily_target_50pct branch ────────────────────────────────


class TestAlertDailyTarget50pct:
    def test_daily_target_50pct_fires_below_hit_threshold(self):
        """pnl_pct=0.03 triggers daily_target_50pct (0.025) but NOT daily_target_hit (0.05)."""
        mgr = AlertManager(notify_fn=None)
        mgr.check_and_alert(
            daily_pnl=300.0,
            daily_pnl_pct=0.03,
            drawdown_pct=0.0,
            consecutive_losses=0,
            portfolio_equity=10_000.0,
        )
        fired = mgr.get_fired_keys()
        assert "daily_target_50pct" in fired
        assert "daily_target_hit" not in fired


# ── alert_manager -- worker no-notify-fn else branch ─────────────────────────


@pytest.mark.asyncio
class TestAlertWorkerNoNotifyFn:
    async def test_worker_with_no_notify_fn_drops_alert_gracefully(self):
        """When notify_fn=None, worker hits else branch (line 261-264) and task_done()."""
        mgr = AlertManager(notify_fn=None)
        mgr.start()

        await mgr._alert_queue.put("test message -- no notifier")
        await asyncio.sleep(0.1)

        await mgr.stop()

        assert mgr._alert_queue.qsize() == 0

    async def test_worker_outer_exception_does_not_kill_worker(self):
        """Worker outer except clause handles unexpected errors in get() path."""
        mgr = AlertManager(notify_fn=None)

        original_get = mgr._alert_queue.get
        get_count = {"n": 0}

        async def _bad_get():
            get_count["n"] += 1
            if get_count["n"] == 1:
                raise RuntimeError("queue error")
            return await original_get()

        mgr.start()
        mgr._alert_queue.get = _bad_get

        await asyncio.sleep(0.15)
        await mgr.stop()

        assert get_count["n"] >= 1

    async def test_stop_cancels_running_worker_and_awaits(self):
        """stop() on a running worker hits cancel + await + CancelledError path (87-88)."""
        mgr = AlertManager(notify_fn=None)
        mgr.start()
        assert mgr._worker_task is not None
        assert not mgr._worker_task.done()

        await mgr.stop()
        assert mgr._worker_task.done()


# ── loss_tracker -- file error paths ─────────────────────────────────────────


class TestLossTrackerFileErrors:
    def test_corrupt_state_file_initializes_empty(self):
        """_load_state with corrupt JSON -> logs error -> returns empty LossTrackerState."""
        tmpdir = tempfile.mkdtemp()
        state_file = Path(tmpdir) / "loss_tracker_state.json"
        state_file.write_text("{{invalid json!!", encoding="utf-8")

        tracker = ConsecutiveLossTracker(data_dir=tmpdir)
        assert tracker.get_consecutive_losses() == 0

    def test_save_state_failure_does_not_raise(self):
        """_save_state failure (read-only dir) is logged, not raised."""
        tmpdir = tempfile.mkdtemp()
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)

        state_file = Path(tmpdir) / "loss_tracker_state.json"
        state_file.write_text("{}", encoding="utf-8")

        import stat

        state_file.chmod(stat.S_IREAD)
        try:
            tracker.record_trade("MES", -10.0)
        finally:
            state_file.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_quarter_threshold_returns_025(self):
        """5 losses (at quarter_threshold=5) -> multiplier returns 0.25."""
        tracker = _make_tracker(
            consecutive_loss_quarter_size=5,
            consecutive_loss_half_size=3,
            consecutive_loss_halt=7,
        )
        for _ in range(5):
            tracker.record_trade("MES", -10.0)

        multiplier = tracker.get_position_size_multiplier()
        assert multiplier == pytest.approx(0.25)

    def test_is_halted_auto_clears_expired_halt(self):
        """is_halted() auto-clears past halt_until timestamp -> returns False."""
        from datetime import datetime, timedelta, timezone

        tmpdir = tempfile.mkdtemp()
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        tracker._state.halt_until = past.isoformat()

        result = tracker.is_halted()
        assert result is False
        assert tracker._state.halt_until is None


# ── margin_monitor -- run_loop ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestMarginMonitorRunLoop:
    async def test_run_loop_calls_check_health_and_exits_cleanly(self):
        """run_loop iterates, calls check_health; CancelledError stops it cleanly."""
        connector = AsyncMock()
        connector.get_account_summary.return_value = {
            "equity": 10_000.0,
            "buying_power": 40_000.0,
            "margin_used": 0.0,
        }
        monitor = MarginMonitorAgent(
            connector=connector,
            utilization_warning=0.25,
            utilization_halt=0.35,
            max_drawdown_pct=8.0,
        )

        task = asyncio.create_task(monitor.run_loop(interval_seconds=0))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert connector.get_account_summary.call_count >= 1

    async def test_run_loop_swallows_check_health_exception(self):
        """run_loop error handler (line 137-138) swallows check_health exceptions."""
        connector = AsyncMock()
        connector.get_account_summary.side_effect = RuntimeError("monitor error")
        monitor = MarginMonitorAgent(
            connector=connector,
            utilization_warning=0.25,
            utilization_halt=0.35,
            max_drawdown_pct=8.0,
        )

        task = asyncio.create_task(monitor.run_loop(interval_seconds=0))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert connector.get_account_summary.call_count >= 1
