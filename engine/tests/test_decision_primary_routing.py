"""Decision-tier primary model routing (JARVIS_DECISION_PRIMARY).

2026-07-17: Anthropic pricing is not viable for always-on decision traffic, and
the Anthropic account is credit-exhausted. Previously the decision tier reached
Gemini only via the credit-exhaustion failover — every decision paid a doomed
Anthropic call first (latency + log noise), and /health still reported anthropic
as the primary leg.

JARVIS_DECISION_PRIMARY names a Gemini model to serve the decision tier
(trader, risk_manager, fund_manager, debate/researchers) as PRIMARY, with
Anthropic/OpenAI still wired behind it. Unset => unchanged behavior.

2026-08-13: extended to accept a kimi-* value too (Amo's explicit, standing
decision to make Kimi the permanent decision-tier primary, superseding the
2026-07-02 Claude-primary/Gemini-failover-only design). Routed via
_resolve_kimi_primary, which mirrors _resolve_google_primary's decision-tier
half exactly. The two are mutually exclusive (the env var can only start with
one prefix at a time).

These tests verify:
  - the resolvers: enrichment agents stay on Gemini flash regardless of which
    decision primary is configured; decision agents follow the env var to
    whichever provider it names; unset means no override for either;
  - non-Gemini/non-Kimi values are inert rather than silently mis-routing (the
    trap JARVIS_LLM_PROVIDER=openai fell into);
  - /health provider reporting names the leg decisions actually take, and keeps
    Anthropic listed behind it (so single_leg_warning stays honest);
  - the ollama provider is unaffected.
"""

from llm import JarvisLLMClient
from llm.client import _LLM_PATH_STATE, get_llm_provider_summary

DECISION_AGENT = "trader"
ENRICHMENT_AGENT = "news_analyst"


def _make_client(tmp_path, monkeypatch, **env):
    """Construct a client with a clean env (provider=anthropic, google key set)."""
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", env.pop("JARVIS_LLM_PROVIDER", "anthropic"))
    monkeypatch.setenv("GOOGLE_API_KEY", env.pop("GOOGLE_API_KEY", "test-google-key"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_DECISION_PRIMARY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_CLAUDE_USE_VERTEX", raising=False)
    monkeypatch.delenv("JARVIS_LLM_VERTEX_FAILOVER", raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    return JarvisLLMClient(api_key="test-key-12345", db_path=str(tmp_path / "costs.db"))


class TestResolver:
    def test_unset_means_no_gemini_primary_for_decisions(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client._resolve_google_primary(DECISION_AGENT) is None

    def test_enrichment_agents_stay_on_flash_when_unset(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client._resolve_google_primary(ENRICHMENT_AGENT) == "gemini-2.5-flash"

    def test_decision_agent_routes_to_configured_pro(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="gemini-2.5-pro")
        assert client._resolve_google_primary(DECISION_AGENT) == "gemini-2.5-pro"

    def test_enrichment_stays_on_flash_even_when_decisions_use_pro(self, tmp_path, monkeypatch):
        # Enrichment is always-on and high-volume; it must not get 4x'd to pro.
        client = _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="gemini-2.5-pro")
        assert client._resolve_google_primary(ENRICHMENT_AGENT) == "gemini-2.5-flash"

    def test_every_decision_agent_follows_the_env(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="gemini-2.5-pro")
        for agent in ("trader", "risk_manager", "fund_manager", "bull_researcher", "advisor_debate"):
            assert client._resolve_google_primary(agent) == "gemini-2.5-pro", agent

    def test_non_gemini_value_is_inert(self, tmp_path, monkeypatch):
        # gpt-4o has no primary route today — better inert than silently
        # mis-routed. (JARVIS_LLM_PROVIDER=openai looked configured for weeks
        # while changing nothing; refuse to repeat that.)
        client = _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="gpt-4o")
        assert client._resolve_google_primary(DECISION_AGENT) is None
        assert client._resolve_google_primary(ENRICHMENT_AGENT) == "gemini-2.5-flash"

    def test_configured_model_must_have_cost_and_context_rows(self, tmp_path, monkeypatch):
        # A primary with no cost row silently zeroes cost tracking.
        client = _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="gemini-2.5-pro")
        model = client._resolve_google_primary(DECISION_AGENT)
        assert JarvisLLMClient.COST_PER_MTOK[model]["input"] > 0
        assert JarvisLLMClient.MODEL_CONTEXT_LIMITS[model] >= 1_000_000


class TestHealthReporting:
    def test_primary_reported_as_gemini_when_configured(self, tmp_path, monkeypatch):
        _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="gemini-2.5-pro")
        assert _LLM_PATH_STATE["primary_provider"] == "gemini"

    def test_anthropic_stays_wired_behind_gemini_primary(self, tmp_path, monkeypatch):
        # single_leg_warning must not fire just because the primary changed —
        # Anthropic is still a real fallback leg behind it.
        _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="gemini-2.5-pro")
        configured = _LLM_PATH_STATE["providers_configured"]
        assert configured[0] == "gemini"
        assert "anthropic" in configured
        assert get_llm_provider_summary()["single_leg_warning"] is False

    def test_gemini_not_double_listed(self, tmp_path, monkeypatch):
        _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="gemini-2.5-pro")
        configured = _LLM_PATH_STATE["providers_configured"]
        assert configured.count("gemini") == 1

    def test_unset_reports_anthropic_primary_unchanged(self, tmp_path, monkeypatch):
        _make_client(tmp_path, monkeypatch)
        assert _LLM_PATH_STATE["primary_provider"] == "anthropic"

    def test_no_google_key_means_no_gemini_primary(self, tmp_path, monkeypatch):
        # Configured but unusable => must not claim gemini as the primary leg.
        client = _make_client(
            tmp_path, monkeypatch, GOOGLE_API_KEY="", JARVIS_DECISION_PRIMARY="gemini-2.5-pro"
        )
        assert client.google_fallback_enabled is False
        assert _LLM_PATH_STATE["primary_provider"] == "anthropic"


class TestKimiResolver:
    def test_unset_means_no_kimi_primary_for_decisions(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, MOONSHOT_API_KEY="test-kimi-key")
        assert client._resolve_kimi_primary(DECISION_AGENT) is None

    def test_enrichment_agents_never_route_to_kimi(self, tmp_path, monkeypatch):
        # Enrichment stays on Gemini flash regardless of the Kimi decision primary.
        client = _make_client(
            tmp_path,
            monkeypatch,
            MOONSHOT_API_KEY="test-kimi-key",
            JARVIS_DECISION_PRIMARY="kimi-k3",
        )
        assert client._resolve_kimi_primary(ENRICHMENT_AGENT) is None
        assert client._resolve_google_primary(ENRICHMENT_AGENT) == "gemini-2.5-flash"

    def test_decision_agent_routes_to_configured_kimi(self, tmp_path, monkeypatch):
        client = _make_client(
            tmp_path,
            monkeypatch,
            MOONSHOT_API_KEY="test-kimi-key",
            JARVIS_DECISION_PRIMARY="kimi-k3",
        )
        assert client._resolve_kimi_primary(DECISION_AGENT) == "kimi-k3"
        # Gemini's own resolver must not also claim the decision tier.
        assert client._resolve_google_primary(DECISION_AGENT) is None

    def test_every_decision_agent_follows_the_env(self, tmp_path, monkeypatch):
        client = _make_client(
            tmp_path,
            monkeypatch,
            MOONSHOT_API_KEY="test-kimi-key",
            JARVIS_DECISION_PRIMARY="kimi-k3",
        )
        for agent in ("trader", "risk_manager", "fund_manager", "bull_researcher", "advisor_debate"):
            assert client._resolve_kimi_primary(agent) == "kimi-k3", agent

    def test_kimi_value_inert_without_key(self, tmp_path, monkeypatch):
        # Named but unusable (no MOONSHOT_API_KEY) => must not claim kimi as primary.
        client = _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="kimi-k3")
        assert client.kimi_fallback_enabled is False
        assert _LLM_PATH_STATE["primary_provider"] == "anthropic"

    def test_configured_model_must_have_cost_and_context_rows(self, tmp_path, monkeypatch):
        client = _make_client(
            tmp_path,
            monkeypatch,
            MOONSHOT_API_KEY="test-kimi-key",
            JARVIS_DECISION_PRIMARY="kimi-k3",
        )
        model = client._resolve_kimi_primary(DECISION_AGENT)
        assert JarvisLLMClient.COST_PER_MTOK[model]["input"] > 0
        assert JarvisLLMClient.MODEL_CONTEXT_LIMITS[model] >= 1_000_000


class TestKimiHealthReporting:
    def test_primary_reported_as_kimi_when_configured(self, tmp_path, monkeypatch):
        _make_client(
            tmp_path,
            monkeypatch,
            MOONSHOT_API_KEY="test-kimi-key",
            JARVIS_DECISION_PRIMARY="kimi-k3",
        )
        assert _LLM_PATH_STATE["primary_provider"] == "kimi"

    def test_anthropic_stays_wired_behind_kimi_primary(self, tmp_path, monkeypatch):
        _make_client(
            tmp_path,
            monkeypatch,
            MOONSHOT_API_KEY="test-kimi-key",
            JARVIS_DECISION_PRIMARY="kimi-k3",
        )
        configured = _LLM_PATH_STATE["providers_configured"]
        assert configured[0] == "kimi"
        assert "anthropic" in configured
        assert get_llm_provider_summary()["single_leg_warning"] is False

    def test_kimi_not_double_listed(self, tmp_path, monkeypatch):
        _make_client(
            tmp_path,
            monkeypatch,
            MOONSHOT_API_KEY="test-kimi-key",
            JARVIS_DECISION_PRIMARY="kimi-k3",
        )
        configured = _LLM_PATH_STATE["providers_configured"]
        assert configured.count("kimi") == 1

    def test_gemini_still_listed_as_a_fallback_leg_behind_kimi_primary(self, tmp_path, monkeypatch):
        # Kimi primary must not crowd out the other real fallback legs.
        _make_client(
            tmp_path,
            monkeypatch,
            MOONSHOT_API_KEY="test-kimi-key",
            JARVIS_DECISION_PRIMARY="kimi-k3",
        )
        configured = _LLM_PATH_STATE["providers_configured"]
        assert "gemini" in configured
        assert "anthropic" in configured


class TestOllamaUnaffected:
    def test_ollama_provider_ignores_decision_primary(self, tmp_path, monkeypatch):
        client = _make_client(
            tmp_path,
            monkeypatch,
            JARVIS_LLM_PROVIDER="ollama",
            JARVIS_DECISION_PRIMARY="gemini-2.5-pro",
        )
        # The call() gate checks provider != "ollama" before consulting the
        # resolver; the reported primary must stay ollama either way.
        assert _LLM_PATH_STATE["primary_provider"] == "ollama"
