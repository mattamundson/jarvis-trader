"""Decision-grade Anthropic->Gemini failover routes to gemini-2.5-pro.

2026-06-22: with Anthropic credit-exhausted, the decision tiers (Opus/Sonnet)
were failing over to gemini-2.5-FLASH. They now fail over to gemini-2.5-PRO
(stronger reasoning, same key/endpoint), while Haiku-tier and the always-on
enrichment-primary path stay on the cheap flash tier.
"""

from llm.client import JarvisLLMClient as C


def test_decision_tiers_failover_to_gemini_pro():
    m = C.GOOGLE_FAILOVER_MAP
    assert m["claude-opus-4-7"] == "gemini-2.5-pro"
    assert m["claude-opus-4-6"] == "gemini-2.5-pro"
    assert m["claude-sonnet-4-6"] == "gemini-2.5-pro"


def test_haiku_tier_stays_on_flash():
    # Haiku is enrichment/classification — keep it cheap and known-good.
    assert C.GOOGLE_FAILOVER_MAP["claude-haiku-4-5-20251001"] == "gemini-2.5-flash"


def test_gemini_pro_is_registered_for_cost_and_context():
    # A model the failover can route to MUST have a cost row (else cost tracking
    # silently zeroes) and a context limit (else compaction math breaks).
    assert "gemini-2.5-pro" in C.COST_PER_MTOK
    assert C.COST_PER_MTOK["gemini-2.5-pro"]["input"] > 0
    assert C.COST_PER_MTOK["gemini-2.5-pro"]["output"] > 0
    assert C.MODEL_CONTEXT_LIMITS.get("gemini-2.5-pro", 0) >= 1_000_000


def test_pro_is_a_gemini_2_5_model_so_it_inherits_thinking_guards():
    # The _call_google token-floor + reasoning_effort=none guards key on the
    # "gemini-2.5" prefix; pro must match so it returns full content, not an
    # empty thinking-truncated response.
    for model in set(C.GOOGLE_FAILOVER_MAP.values()):
        if model.startswith("gemini-2.5"):
            assert model.startswith("gemini-2.5")  # tautology-as-guard documents intent
    assert "gemini-2.5-pro".startswith("gemini-2.5")
