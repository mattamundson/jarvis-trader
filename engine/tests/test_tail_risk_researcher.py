"""
Unit tests for TailRiskResearcherAgent (Novel #1 from strategy synthesis).

Covers:
  * JSON parsing (clean, markdown-fenced, malformed)
  * Score/multiplier clamping at bounds
  * Veto-honesty enforcement (score≥0.9 forces veto, veto forces 0 size)
  * Safe-fail behaviour (LLM error → conservative default report)
  * Successful end-to-end analyze() via mocked httpx transport
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agents.tail_risk_researcher import (
    TailRiskReport,
    TailRiskResearcherAgent,
)

# ── Pure-function tests ──────────────────────────────────────────────────────

def test_parse_json_plain():
    raw = '{"tail_risk_score": 0.4, "veto": false}'
    parsed = TailRiskResearcherAgent._parse_json(raw)
    assert parsed["tail_risk_score"] == 0.4
    assert parsed["veto"] is False


def test_parse_json_markdown_fenced():
    raw = '```json\n{"tail_risk_score": 0.7, "size_multiplier": 0.6}\n```'
    parsed = TailRiskResearcherAgent._parse_json(raw)
    assert parsed["tail_risk_score"] == 0.7
    assert parsed["size_multiplier"] == 0.6


def test_parse_json_malformed_returns_empty():
    raw = "not json at all { broken"
    parsed = TailRiskResearcherAgent._parse_json(raw)
    assert parsed == {}


def test_clamp_within_bounds():
    assert TailRiskResearcherAgent._clamp(0.5, 0.0, 1.0) == 0.5


def test_clamp_below_bound():
    assert TailRiskResearcherAgent._clamp(-0.5, 0.0, 1.0) == 0.0


def test_clamp_above_bound():
    assert TailRiskResearcherAgent._clamp(1.5, 0.0, 1.0) == 1.0


def test_safe_float_with_none():
    assert TailRiskResearcherAgent._safe_float(None, 0.42) == 0.42


def test_safe_float_with_string_value():
    assert TailRiskResearcherAgent._safe_float("0.7", 0.0) == 0.7


def test_safe_float_invalid_returns_default():
    assert TailRiskResearcherAgent._safe_float("not_a_number", 1.0) == 1.0


def test_safe_float_or_none_passthrough():
    assert TailRiskResearcherAgent._safe_float_or_none(None) is None
    assert TailRiskResearcherAgent._safe_float_or_none("12.5") == 12.5
    assert TailRiskResearcherAgent._safe_float_or_none("xyz") is None


# ── Build-report semantics ───────────────────────────────────────────────────

def test_build_report_normal_values():
    agent = TailRiskResearcherAgent(api_key="test")
    payload = {
        "tail_risk_score": 0.4,
        "size_multiplier": 0.8,
        "veto": False,
        "worst_case_drawdown_usd": 250.0,
        "key_risks": ["EIA inventory at 9:30 CT", "MCL gap risk on geopolitics"],
        "recommendation": "SIZE_DOWN",
        "reasoning": "Moderate event-window risk; downsize 20%.",
    }
    report = agent._build_report("MCL", payload)
    assert report.symbol == "MCL"
    assert report.tail_risk_score == 0.4
    assert report.size_multiplier == 0.8
    assert report.veto is False
    assert report.worst_case_drawdown_usd == 250.0
    assert len(report.key_risks) == 2
    assert report.recommendation == "SIZE_DOWN"


def test_build_report_high_score_forces_veto():
    """If LLM returns tail_risk_score≥0.9 but veto=False, agent overrides to veto."""
    agent = TailRiskResearcherAgent(api_key="test")
    payload = {
        "tail_risk_score": 0.95,
        "size_multiplier": 0.5,  # LLM contradicting itself — should be 0
        "veto": False,           # forced to True
        "key_risks": ["Catastrophic gap risk"],
        "recommendation": "SIZE_DOWN",
        "reasoning": "model was inconsistent",
    }
    report = agent._build_report("MCL", payload)
    assert report.veto is True, "score≥0.9 must force veto"
    assert report.size_multiplier == 0.0, "veto must force size_multiplier to 0"
    assert report.tail_risk_score == 0.95


def test_build_report_veto_forces_zero_size():
    """If LLM returns veto=True but size_multiplier>0, agent zeroes it."""
    agent = TailRiskResearcherAgent(api_key="test")
    payload = {
        "tail_risk_score": 0.6,
        "size_multiplier": 0.7,
        "veto": True,
        "recommendation": "VETO",
        "reasoning": "FOMC in 4 hours",
    }
    report = agent._build_report("MES", payload)
    assert report.veto is True
    assert report.size_multiplier == 0.0


def test_build_report_clamps_out_of_range_values():
    """Defensive clamping when the LLM returns nonsense numbers."""
    agent = TailRiskResearcherAgent(api_key="test")
    payload = {
        "tail_risk_score": 1.5,    # > 1.0
        "size_multiplier": -0.3,   # < 0.0
        "veto": False,
    }
    report = agent._build_report("MNQ", payload)
    assert report.tail_risk_score == 1.0
    assert report.size_multiplier == 0.0
    # tail_risk_score clamped to exactly 1.0 — that triggers the "≥0.9 → veto" rule
    assert report.veto is True


def test_build_report_missing_fields_uses_defaults():
    """Empty LLM response should still produce a valid report (PROCEED, no veto)."""
    agent = TailRiskResearcherAgent(api_key="test")
    report = agent._build_report("MES", {})
    assert report.tail_risk_score == 0.0
    assert report.size_multiplier == 1.0
    assert report.veto is False
    assert report.key_risks == []


def test_safe_report_is_conservative_pass_through():
    """Safe report must NEVER veto on its own — defers to bull/bear."""
    agent = TailRiskResearcherAgent(api_key="test")
    report = agent._safe_report("MCL")
    assert report.veto is False
    assert report.size_multiplier == 1.0
    assert report.tail_risk_score == 0.0
    assert "PROCEED" in report.recommendation


# ── Report serialisation ─────────────────────────────────────────────────────

def test_to_dict_roundtrip():
    report = TailRiskReport(
        symbol="MCL",
        timestamp=datetime(2026, 4, 16, 22, 50),
        tail_risk_score=0.4,
        size_multiplier=0.8,
        veto=False,
        worst_case_drawdown_usd=300.0,
        key_risks=["risk a", "risk b"],
        recommendation="SIZE_DOWN",
        reasoning="moderate exposure",
    )
    d = report.to_dict()
    assert d["symbol"] == "MCL"
    assert d["timestamp"] == "2026-04-16T22:50:00"
    assert d["tail_risk_score"] == 0.4
    assert d["key_risks"] == ["risk a", "risk b"]


# ── End-to-end analyze() via mocked httpx ────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_success_path():
    """Mock the Anthropic API and confirm analyze() returns a populated report."""
    fake_response_text = json.dumps({
        "tail_risk_score": 0.55,
        "size_multiplier": 0.75,
        "veto": False,
        "worst_case_drawdown_usd": 400.0,
        "key_risks": [
            "EIA crude inventory release at 9:30 CT (12h away)",
            "MCL ATR=1.2 vs stop distance=0.8 → adverse-excursion ratio 1.5x",
            "OPEC commentary risk on $84.20 entry",
        ],
        "recommendation": "SIZE_DOWN",
        "reasoning": "Pre-EIA window plus tight stop creates 1.5x asymmetric MAE.",
    })
    fake_payload = {"content": [{"text": fake_response_text}]}

    async def _mock_post(*_args, **_kwargs):
        # Return a minimal httpx-like response object
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        return httpx.Response(200, json=fake_payload, request=request)

    agent = TailRiskResearcherAgent(api_key="test-key")
    with patch.object(httpx.AsyncClient, "post", new=AsyncMock(side_effect=_mock_post)):
        report = await agent.analyze(
            "MCL",
            analyst_reports={"technical": {"signal": -0.6}},
            proposed_trade={"entry": 84.20, "stop": 84.80, "side": "short", "contracts": 1},
        )

    assert report.symbol == "MCL"
    assert report.tail_risk_score == 0.55
    assert report.size_multiplier == 0.75
    assert report.veto is False
    assert report.worst_case_drawdown_usd == 400.0
    assert len(report.key_risks) == 3
    assert report.recommendation == "SIZE_DOWN"


@pytest.mark.asyncio
async def test_analyze_failure_returns_safe_report():
    """When the HTTP call raises, analyze() must return a conservative default."""
    async def _mock_post(*_args, **_kwargs):
        raise httpx.ConnectError("simulated network failure")

    agent = TailRiskResearcherAgent(api_key="test-key")
    with patch.object(httpx.AsyncClient, "post", new=AsyncMock(side_effect=_mock_post)):
        report = await agent.analyze("MCL", analyst_reports={})

    assert report.veto is False
    assert report.size_multiplier == 1.0
    assert report.tail_risk_score == 0.0
    assert "unavailable" in report.reasoning.lower()
