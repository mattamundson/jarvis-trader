"""I1: digest surfaces LLM provider health; alert on unhealthy primary."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord.digest_generator import _assess_llm_health  # noqa: E402


def _payload(primary_healthy: bool, active: str = "gemini") -> dict:
    return {
        "llm_path_healthy": True,
        "google_fallback_count": 4,
        "vertex_failover_count": 0,
        "llm_providers": {
            "active_provider": active,
            "primary_provider": "anthropic",
            "providers_available": 3,
            "primary_healthy": primary_healthy,
        },
    }


class TestAssessLlmHealth:
    def test_unhealthy_primary_alerts(self):
        report = _assess_llm_health(_payload(primary_healthy=False))
        assert report["alert"] is True
        assert report["primary_healthy"] is False
        assert report["active_provider"] == "gemini"
        assert report["google_fallback_count"] == 4

    def test_healthy_primary_no_alert(self):
        report = _assess_llm_health(_payload(primary_healthy=True, active="anthropic"))
        assert report["alert"] is False
        assert report["primary_healthy"] is True

    def test_missing_providers_block_defaults_healthy(self):
        """Old engines without llm_providers must not false-alert."""
        report = _assess_llm_health({"llm_path_healthy": True})
        assert report["alert"] is False
        assert report["active_provider"] is None

    def test_engine_reachable_flag_set(self):
        report = _assess_llm_health(_payload(primary_healthy=False))
        assert report["engine_reachable"] is True
