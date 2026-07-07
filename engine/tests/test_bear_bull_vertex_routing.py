"""Task 10: Bear/Bull researchers route debate calls through JarvisLLMClient.

Previously these agents bypassed central routing with their own httpx POST to
api.anthropic.com. They now go through the shared client, so they inherit Vertex
routing/failover/health/cost. These tests patch JarvisLLMClient with a recorder,
so they need no network or credentials.
"""

from llm.client import LLMCallResult


class _RecordingLLMClient:
    """Stand-in for JarvisLLMClient: records call() args, returns canned content."""

    def __init__(self, *args, **kwargs):
        self.calls = []
        self.content = "{}"

    async def call(self, model, system, messages, max_tokens, agent_name="unknown", **kwargs):
        self.calls.append(
            {
                "model": model,
                "system": system,
                "agent_name": agent_name,
                "max_tokens": max_tokens,
            }
        )
        return LLMCallResult(
            success=True,
            model=model,
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.0,
            latency_ms=1,
            retries=0,
            content=self.content,
        )


async def test_bear_analyze_routes_through_client(monkeypatch):
    monkeypatch.setattr("llm.client.JarvisLLMClient", _RecordingLLMClient)
    from agents.bear_researcher import BearReport, BearResearcherAgent

    agent = BearResearcherAgent(api_key="x")
    agent._llm_client.content = (
        '{"bear_thesis":"weak breakout","key_risks":["overbought"],'
        '"downside_target":10.5,"time_horizon":"swing","conviction":0.7,'
        '"counterargument_response":"resp"}'
    )
    report = await agent.analyze("ES", {"technical": {"stc": 80}})
    assert isinstance(report, BearReport)
    assert report.bear_thesis == "weak breakout"
    assert report.conviction == 0.7
    assert report.downside_target == 10.5
    last = agent._llm_client.calls[-1]
    assert last["agent_name"] == "bear_researcher"
    assert last["model"] == "claude-sonnet-4-6"
    assert last["system"]  # analyze passes the SYSTEM_PROMPT


async def test_bull_analyze_routes_through_client(monkeypatch):
    monkeypatch.setattr("llm.client.JarvisLLMClient", _RecordingLLMClient)
    from agents.bull_researcher import BullReport, BullResearcherAgent

    agent = BullResearcherAgent(api_key="x")
    agent._llm_client.content = (
        '{"bull_thesis":"strong trend","key_evidence":["higher highs"],'
        '"price_target":120.0,"time_horizon":"swing","conviction":0.6,'
        '"counterargument_response":"resp"}'
    )
    report = await agent.analyze("ES", {"technical": {"stc": 20}})
    assert isinstance(report, BullReport)
    assert report.bull_thesis == "strong trend"
    assert report.price_target == 120.0
    last = agent._llm_client.calls[-1]
    assert last["agent_name"] == "bull_researcher"
    assert last["model"] == "claude-sonnet-4-6"


async def test_bear_call_llm_uses_client_and_weights(monkeypatch):
    monkeypatch.setattr("llm.client.JarvisLLMClient", _RecordingLLMClient)
    from agents.bear_researcher import BearResearcherAgent

    agent = BearResearcherAgent(api_key="x")
    agent._llm_client.content = (
        "ASSESSMENT: SCORE: 6/10 | EVIDENCE_COUNT: 4 | EVIDENCE_QUALITY: high"
    )
    out = await agent.call_llm("score the bull case")
    # The evidence-weighting enhancement still runs on the client's response.
    assert "WEIGHTED_SCORE" in out
    last = agent._llm_client.calls[-1]
    assert last["agent_name"] == "bear_researcher"
    assert last["max_tokens"] == 256


async def test_call_llm_graceful_on_failure(monkeypatch):
    monkeypatch.setattr("llm.client.JarvisLLMClient", _RecordingLLMClient)
    from agents.bull_researcher import BullResearcherAgent

    agent = BullResearcherAgent(api_key="x")

    async def _fail(*a, **k):
        return LLMCallResult(
            success=False,
            model="claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=1,
            retries=3,
            error="boom",
        )

    agent._llm_client.call = _fail
    # _call_llm swallows failures and returns "" so the debate never crashes.
    out = await agent._call_llm("rebut this")
    assert out == ""
