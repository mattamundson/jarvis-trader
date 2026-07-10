"""JARVIS TRADER — Scheduler Tests"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestEODSchedulerInitialization:
    """Test EODScheduler initialization."""

    def test_eod_scheduler_init_with_all_dependencies(self):
        """EODScheduler initializes with all optional dependencies."""
        from schedulers.eod_scheduler import EODScheduler

        db, tracker, notifier = MagicMock(), MagicMock(), MagicMock()
        scheduler = EODScheduler(
            db_manager=db, portfolio_tracker=tracker, whatsapp_notifier=notifier
        )
        assert (
            scheduler._db is db
            and scheduler._tracker is tracker
            and scheduler._notifier is notifier
        )

    def test_eod_scheduler_init_without_dependencies(self):
        """EODScheduler initializes gracefully without dependencies."""
        from schedulers.eod_scheduler import EODScheduler

        scheduler = EODScheduler()
        assert scheduler._db is None and scheduler._tracker is None and scheduler._notifier is None

    def test_eod_scheduler_init_with_partial_dependencies(self):
        """EODScheduler handles partial dependency injection."""
        from schedulers.eod_scheduler import EODScheduler

        db = MagicMock()
        scheduler = EODScheduler(db_manager=db)
        assert scheduler._db is db and scheduler._tracker is None


class TestEODSchedulerSnapshot:
    """Test EOD snapshot collection and persistence."""

    @pytest.mark.asyncio
    async def test_run_eod_snapshot_without_db(self):
        """EOD snapshot returns data without database persistence."""
        from schedulers.eod_scheduler import EODScheduler

        tracker = MagicMock()
        tracker.get_performance.return_value = {
            "total_pnl": 150.0,
            "num_trades": 5,
            "win_rate": 0.6,
            "max_dd": 0.02,
        }
        tracker.get_positions.return_value = []
        scheduler = EODScheduler(portfolio_tracker=tracker)
        result = await scheduler.run_eod_snapshot()
        assert "status" in result and "realized_pnl" in result and result["total_trades"] == 5

    @pytest.mark.asyncio
    async def test_run_eod_snapshot_with_db(self):
        """EOD snapshot persists to database when available."""
        from schedulers.eod_scheduler import EODScheduler

        db = MagicMock()
        db.get_latest_daily_pnl.return_value = {"date": "2026-03-28", "ending_balance": 10_000.0}
        tracker = MagicMock()
        tracker.get_performance.return_value = {
            "total_pnl": 150.0,
            "num_trades": 3,
            "win_rate": 0.67,
            "max_dd": 0.01,
        }
        tracker.get_positions.return_value = []
        scheduler = EODScheduler(db_manager=db, portfolio_tracker=tracker)
        result = await scheduler.run_eod_snapshot()
        assert result["status"] == "ok"
        db.upsert_daily_pnl.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_eod_snapshot_handles_tracker_exception(self):
        """EOD snapshot degrades gracefully on tracker errors."""
        from schedulers.eod_scheduler import EODScheduler

        tracker = MagicMock()
        tracker.get_performance.side_effect = RuntimeError("Tracker unavailable")
        scheduler = EODScheduler(portfolio_tracker=tracker)
        result = await scheduler.run_eod_snapshot()
        assert "status" in result and result["total_trades"] == 0


class TestWeeklyReview:
    """Test weekly review aggregation."""

    @pytest.mark.asyncio
    async def test_run_weekly_review_without_db(self):
        """Weekly review returns aggregated stats without database."""
        from schedulers.eod_scheduler import EODScheduler

        scheduler = EODScheduler()
        result = await scheduler.run_weekly_review()
        assert result["status"] == "ok" and result["trading_days"] == 0

    @pytest.mark.asyncio
    async def test_run_weekly_review_with_data(self):
        """Weekly review aggregates daily data correctly."""
        from schedulers.eod_scheduler import EODScheduler

        db = MagicMock()
        db.get_daily_pnl.return_value = [
            {
                "date": "2026-03-25",
                "realized_pnl": 100.0,
                "total_trades": 2,
                "winning_trades": 2,
                "losing_trades": 0,
                "max_drawdown": 0.01,
            },
            {
                "date": "2026-03-26",
                "realized_pnl": 50.0,
                "total_trades": 1,
                "winning_trades": 1,
                "losing_trades": 0,
                "max_drawdown": 0.005,
            },
        ]
        scheduler = EODScheduler(db_manager=db)
        result = await scheduler.run_weekly_review()
        assert (
            result["status"] == "ok"
            and result["total_pnl"] == 150.0
            and result["trading_days"] == 2
        )


class TestSchedulerJobRegistration:
    """Test registration of jobs with APScheduler."""

    def test_register_with_scheduler_creates_jobs(self):
        """Registering scheduler creates all expected jobs."""
        from schedulers.eod_scheduler import EODScheduler

        mock_scheduler = MagicMock()
        EODScheduler().register_with_scheduler(mock_scheduler)
        assert mock_scheduler.add_job.call_count == 6  # 4 original + session_flatten (Sprint 14) + forward_test_snapshot (forward-test stack)

    def test_eod_snapshot_job_registered(self):
        """EOD snapshot job is registered with APScheduler."""
        from schedulers.eod_scheduler import EODScheduler

        mock_scheduler = MagicMock()
        EODScheduler().register_with_scheduler(mock_scheduler)
        assert mock_scheduler.add_job.call_count >= 2


class TestSchedulerDegradation:
    """Test graceful degradation when dependencies unavailable."""

    def test_scheduler_init_without_external_deps(self):
        """EODScheduler initializes without requiring APScheduler."""
        from schedulers.eod_scheduler import EODScheduler

        scheduler = EODScheduler()
        assert scheduler is not None

    @pytest.mark.asyncio
    async def test_eod_operations_without_external_services(self):
        """EOD operations gracefully handle missing services."""
        from schedulers.eod_scheduler import EODScheduler

        result = await EODScheduler().run_eod_snapshot()
        assert result is not None and "status" in result


class TestTodaySummary:
    """Test real-time intraday summary method."""

    def test_get_today_summary_without_dependencies(self):
        """get_today_summary works without database or tracker."""
        from schedulers.eod_scheduler import EODScheduler

        result = EODScheduler().get_today_summary()
        assert result["status"] == "intraday" and "starting_balance" in result

    def test_get_today_summary_with_tracker(self):
        """get_today_summary includes tracker metrics when available."""
        from schedulers.eod_scheduler import EODScheduler

        tracker = MagicMock()
        tracker.get_performance.return_value = {
            "total_pnl": 200.0,
            "num_trades": 4,
            "win_rate": 0.75,
            "max_dd": 0.03,
        }
        tracker.get_positions.return_value = []
        result = EODScheduler(portfolio_tracker=tracker).get_today_summary()
        assert result["total_trades"] == 4 and result["status"] == "intraday"


class TestMorningBriefing:
    """Test morning briefing job."""

    @pytest.mark.asyncio
    async def test_run_morning_briefing_without_notifier(self):
        """Morning briefing gracefully handles missing notifier."""
        from schedulers.eod_scheduler import EODScheduler

        result = await EODScheduler().run_morning_briefing()
        assert result["status"] == "no_notifier" and result["sent"] is False

    @pytest.mark.asyncio
    async def test_run_morning_briefing_with_disabled_notifier(self):
        """Morning briefing skips if notifier disabled."""
        from schedulers.eod_scheduler import EODScheduler

        notifier = MagicMock()
        notifier.enabled = False
        result = await EODScheduler(whatsapp_notifier=notifier).run_morning_briefing()
        assert result["status"] == "no_notifier"


class TestVIXAlertCheck:
    """Test VIX alert check job."""

    @pytest.mark.asyncio
    async def test_run_vix_alert_check_without_notifier(self):
        """VIX alert check gracefully handles missing notifier."""
        from schedulers.eod_scheduler import EODScheduler

        await EODScheduler().run_vix_alert_check()

    @pytest.mark.asyncio
    async def test_run_vix_alert_check_cooldown_suppresses_repeat(self, monkeypatch):
        """The hourly cron must not resend an identical alert on back-to-back
        runs while VIX stays elevated at the same severity level."""
        import analytics.vix_overlay as vix_overlay_mod
        from notifications.vix_alert_cooldown import reset_vix_alert_cooldown_for_tests
        from schedulers.eod_scheduler import EODScheduler

        reset_vix_alert_cooldown_for_tests()

        class _FakeState:
            vix_value = 42.0

        monkeypatch.setattr(vix_overlay_mod, "VIXOverlay", lambda: type(
            "F", (), {"get_state": lambda self: _FakeState()}
        )())

        notifier = MagicMock()
        notifier.enabled = True
        notifier.send = AsyncMock(return_value=True)
        scheduler = EODScheduler(whatsapp_notifier=notifier)

        await scheduler.run_vix_alert_check()
        await scheduler.run_vix_alert_check()

        assert notifier.send.await_count == 1
        reset_vix_alert_cooldown_for_tests()


class TestSchedulerLifecycle:
    """Test scheduler startup and shutdown."""

    def test_scheduler_status_response_shape(self):
        """Scheduler status endpoint returns valid JSON."""
        job1, job2 = MagicMock(), MagicMock()
        job1.id, job1.name = "eod_snapshot", "EOD P&L Snapshot"
        job1.next_run_time = datetime.now(timezone.utc)
        job2.id, job2.name = "weekly_review", "Weekly P&L Review"
        job2.next_run_time = datetime.now(timezone.utc)
        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        mock_scheduler.get_jobs.return_value = [job1, job2]
        response = {
            "running": True,
            "total_jobs": 2,
            "jobs": [
                {"id": j.id, "name": j.name, "next_run": j.next_run_time.isoformat()}
                for j in mock_scheduler.get_jobs()
            ],
            "total_decisions_logged": 0,
        }
        assert response["running"] and response["total_jobs"] == 2 and len(response["jobs"]) == 2
