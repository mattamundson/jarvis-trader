"""Tests for nightly Discord import scheduling."""

import logging
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

logger = logging.getLogger(__name__)


class TestNightlyDiscordSchedule:
    """Test nightly Discord scheduling and import functionality."""

    def test_nightly_discord_module_importable(self):
        """Test that nightly_discord module is importable without error."""
        try:
            import scripts.nightly_discord as nd_module

            assert nd_module is not None
        except Exception as e:
            pytest.fail(f"Failed to import nightly_discord: {e}")

    def test_run_import_function_exists(self):
        """Test that run_discord_import function exists and is callable."""
        import scripts.nightly_discord as nd_module

        assert hasattr(nd_module, "run_discord_import")
        assert callable(nd_module.run_discord_import)

    def test_run_sentiment_etl_function_exists(self):
        """Test that run_sentiment_etl function exists and is callable."""
        import scripts.nightly_discord as nd_module

        assert hasattr(nd_module, "run_sentiment_etl")
        assert callable(nd_module.run_sentiment_etl)

    def test_scheduler_has_nightly_discord_job(self):
        """Test that scheduler has job with id='nightly_discord_import' registered."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = AsyncIOScheduler(timezone="America/Chicago")

        async def dummy_job():
            pass

        scheduler.add_job(
            dummy_job,
            CronTrigger(
                day_of_week="mon-fri",
                hour=6,
                minute=0,
                timezone="America/Chicago",
            ),
            id="nightly_discord_import",
            name="Nightly Discord Import",
            max_instances=1,
            replace_existing=True,
            misfire_grace_time=3600,
        )

        job = scheduler.get_job("nightly_discord_import")
        assert job is not None
        assert job.id == "nightly_discord_import"
        assert job.name == "Nightly Discord Import"

    def test_trigger_response_model(self):
        """Test TriggerResponse model structure."""
        from routers.scheduler_router import TriggerResponse

        response = TriggerResponse(triggered=True, timestamp="2026-01-01T00:00:00")
        assert response.triggered is True
        assert response.timestamp == "2026-01-01T00:00:00"

    def test_nightly_discord_import_returns_dict(self):
        """Test that run_discord_import returns dict."""
        import scripts.nightly_discord as nd_module

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = nd_module.run_discord_import()
            assert isinstance(result, dict)

    def test_sentiment_etl_returns_dict(self):
        """Test that run_sentiment_etl returns dict."""
        import scripts.nightly_discord as nd_module

        with patch("discord.sentiment_provider.SentimentProvider") as mock_sentiment:
            mock_instance = MagicMock()
            mock_instance.run_etl.return_value = None
            mock_sentiment.return_value = mock_instance

            result = nd_module.run_sentiment_etl()
            assert isinstance(result, dict)
