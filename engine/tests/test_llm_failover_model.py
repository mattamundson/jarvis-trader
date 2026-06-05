"""
Regression guard for the Anthropic -> Gemini failover model map.

2026-06-04: Haiku-tier agents (news_analyst, social_analyst) mapped to
gemini-2.0-flash, which 404s at the OpenAI-compat endpoint (resource-not-found,
not a transient 5xx) while gemini-2.5-flash returns 200 with the same key. With
Anthropic credit-exhausted, that silently broke failover for every Haiku-tier
agent. These tests assert the map only targets the known-good model so the
404 path cannot be reintroduced.
"""

from llm import JarvisLLMClient


def test_no_failover_target_uses_gemini_2_0_flash():
    # gemini-2.0-flash 404s at the OpenAI-compat endpoint — never a failover target.
    targets = set(JarvisLLMClient.GOOGLE_FAILOVER_MAP.values())
    assert "gemini-2.0-flash" not in targets


def test_haiku_maps_to_known_good_model():
    assert (
        JarvisLLMClient.GOOGLE_FAILOVER_MAP["claude-haiku-4-5-20251001"]
        == "gemini-2.5-flash"
    )


def test_all_tiers_have_a_failover_target():
    for model, target in JarvisLLMClient.GOOGLE_FAILOVER_MAP.items():
        assert target, f"{model} has no Gemini failover target"
        assert target.startswith("gemini-"), f"{model} -> {target} is not a Gemini model"
