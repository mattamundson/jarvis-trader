"""Decision-tier primary model routing for Kimi K3 (JARVIS_DECISION_PRIMARY=kimi-k3).

2026-07-18: Kimi K3 (Moonshot AI) added as a second selectable decision-tier
PRIMARY alongside gemini-2.5-pro (see test_decision_primary_routing.py for the
Gemini version — this file mirrors its structure for the Kimi/Moonshot leg).

JARVIS_DECISION_PRIMARY names "kimi-k3" to serve the decision tier (trader,
risk_manager, fund_manager, debate/researchers) as PRIMARY, with
Anthropic/OpenAI still wired behind it. Unset (or a gemini-* value) => no
Kimi-primary routing at all. Unlike Gemini, Kimi is not part of the Anthropic
credit-exhaustion failover cascade — it only serves when explicitly chosen.

These tests verify:
  - the resolver: enrichment agents never route to Kimi (stay on Gemini flash
    logic upstream), decision agents follow the env var, and unset/gemini
    values mean no Kimi-primary routing;
  - a missing MOONSHOT_API_KEY means Kimi cannot be primary even if named;
  - /health provider reporting names "kimi" as the active leg and keeps
    Anthropic listed behind it (single_leg_warning stays honest);
  - Kimi and Gemini decision-primary are mutually exclusive per the single
    JARVIS_DECISION_PRIMARY value;
  - the ollama provider is unaffected;
  - the configured model has real cost/context rows (no silent zero-cost).
"""

from llm import JarvisLLMClient
from llm.client import _LLM_PATH_STATE, get_llm_provider_summary

DECISION_AGENT = "trader"
ENRICHMENT_AGENT = "news_analyst"


def _make_client(tmp_path, monkeypatch, **env):
    """Construct a client with a clean env (provider=anthropic, kimi key set)."""
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", env.pop("JARVIS_LLM_PROVIDER", "anthropic"))
    monkeypatch.setenv("MOONSHOT_API_KEY", env.pop("MOONSHOT_API_KEY", "test-moonshot-key"))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_DECISION_PRIMARY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_CLAUDE_USE_VERTEX", raising=False)
    monkeypatch.delenv("JARVIS_LLM_VERTEX_FAILOVER", raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    return JarvisLLMClient(api_key="test-key-12345", db_path=str(tmp_path / "costs.db"))


class TestResolver:
    def test_unset_means_no_kimi_primary_for_decisions(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client._resolve_kimi_primary(DECISION_AGENT) is None

    def test_enrichment_agents_never_route_to_kimi(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="kimi-k3")
        assert client._resolve_kimi_primary(ENRICHMENT_AGENT) is None

    def test_decision_agent_routes_to_configured_kimi(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="kimi-k3")
        assert client._resolve_kimi_primary(DECISION_AGENT) == "kimi-k3"

    def test_every_decision_agent_follows_the_env(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="kimi-k3")
        for agent in ("trader", "risk_manager", "fund_manager", "bull_researcher", "advisor_debate"):
            assert client._resolve_kimi_primary(agent) == "kimi-k3", agent

    def test_gemini_value_does_not_trigger_kimi_resolver(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="gemini-2.5-pro")
        assert client._resolve_kimi_primary(DECISION_AGENT) is None

    def test_configured_model_must_have_cost_and_context_rows(self, tmp_path, monkeypatch):
        # A primary with no cost row silently zeroes cost tracking.
        client = _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="kimi-k3")
        model = client._resolve_kimi_primary(DECISION_AGENT)
        assert JarvisLLMClient.COST_PER_MTOK[model]["input"] > 0
        assert JarvisLLMClient.MODEL_CONTEXT_LIMITS[model] >= 1_000_000


class TestHealthReporting:
    def test_primary_reported_as_kimi_when_configured(self, tmp_path, monkeypatch):
        _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="kimi-k3")
        assert _LLM_PATH_STATE["primary_provider"] == "kimi"

    def test_anthropic_stays_wired_behind_kimi_primary(self, tmp_path, monkeypatch):
        # single_leg_warning must not fire just because the primary changed —
        # Anthropic is still a real fallback leg behind it.
        _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="kimi-k3")
        configured = _LLM_PATH_STATE["providers_configured"]
        assert configured[0] == "kimi"
        assert "anthropic" in configured
        assert get_llm_provider_summary()["single_leg_warning"] is False

    def test_kimi_not_double_listed(self, tmp_path, monkeypatch):
        _make_client(tmp_path, monkeypatch, JARVIS_DECISION_PRIMARY="kimi-k3")
        configured = _LLM_PATH_STATE["providers_configured"]
        assert configured.count("kimi") == 1

    def test_no_moonshot_key_means_no_kimi_primary(self, tmp_path, monkeypatch):
        # Named but unusable => must not claim kimi as the primary leg.
        client = _make_client(
            tmp_path, monkeypatch, MOONSHOT_API_KEY="", JARVIS_DECISION_PRIMARY="kimi-k3"
        )
        assert client.kimi_api_key == ""
        assert _LLM_PATH_STATE["primary_provider"] == "anthropic"

    def test_kimi_and_gemini_primary_are_mutually_exclusive(self, tmp_path, monkeypatch):
        # A single JARVIS_DECISION_PRIMARY value can only start with one
        # prefix — configuring kimi-k3 must not also claim gemini as PRIMARY,
        # even though Gemini legitimately still appears as a real fallback
        # leg behind it when GOOGLE_API_KEY is also configured.
        _make_client(
            tmp_path,
            monkeypatch,
            GOOGLE_API_KEY="test-google-key",
            JARVIS_DECISION_PRIMARY="kimi-k3",
        )
        assert _LLM_PATH_STATE["primary_provider"] == "kimi"
        configured = _LLM_PATH_STATE["providers_configured"]
        assert configured[0] == "kimi"
        assert configured.count("kimi") == 1
        assert configured.count("gemini") <= 1


class TestOllamaUnaffected:
    def test_ollama_provider_ignores_kimi_decision_primary(self, tmp_path, monkeypatch):
        client = _make_client(
            tmp_path,
            monkeypatch,
            JARVIS_LLM_PROVIDER="ollama",
            JARVIS_DECISION_PRIMARY="kimi-k3",
        )
        assert _LLM_PATH_STATE["primary_provider"] == "ollama"
        assert client.kimi_api_key == "test-moonshot-key"  # configured but inert under ollama
