"""
Tests for POST /jarvis/ask — natural-language command bridge.

Strategy: mount the jarvis_router in a minimal FastAPI app (no full main.py import).
This avoids the heavy openbb / apscheduler import cost that causes timeouts in the
full-app fixture pattern.

Tests exercise:
- Intent routing (health, bookmark_search, unknown, refused)
- Hardcoded refusal list (returns 200 with intent='refused', NOT a 4xx)
- JSONL metadata log written without PII
- Unknown-intent response lists supported intents

Run with:
    engine/.venv/Scripts/python -m pytest engine/tests/test_jarvis_router.py -v
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import types
import unittest.mock as mock
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Path setup ────────────────────────────────────────────────────────────────

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

# ── Stub heavy deps at module load time ──────────────────────────────────────
# These must be in place before routers.jarvis_router is imported because it
# imports from api.models and services.jarvis_analysis, both of which pull in
# google.genai / yfinance transitively.


def _install_stubs() -> None:
    """Install minimal stubs for dependencies not available in the test env."""
    # google / google.genai
    if "google" not in sys.modules:
        fake_google = types.ModuleType("google")
        fake_genai = types.ModuleType("google.genai")
        fake_genai.Client = object
        fake_google.genai = fake_genai
        sys.modules["google"] = fake_google
        sys.modules["google.genai"] = fake_genai

    # yfinance
    if "yfinance" not in sys.modules:
        fake_yf = types.ModuleType("yfinance")

        class _Ticker:
            def __init__(self, *a, **kw):
                pass

            def history(self, *a, **kw):
                raise RuntimeError("yfinance not available in test")

        fake_yf.Ticker = _Ticker
        sys.modules["yfinance"] = fake_yf

    # Stub services.jarvis_analysis so the router imports cleanly without Gemini
    if "services" not in sys.modules:
        sys.modules["services"] = types.ModuleType("services")
    if "services.jarvis_analysis" not in sys.modules:
        fake_ja = types.ModuleType("services.jarvis_analysis")
        fake_ja.analyze_symbol = lambda symbol, period: f"Synthetic analysis for {symbol}"
        fake_ja.MODEL_NAME = "test-model"
        sys.modules["services.jarvis_analysis"] = fake_ja
        sys.modules["services"].jarvis_analysis = fake_ja  # type: ignore[attr-defined]

    # Stub api.models (JarvisQuickAnalysisRequest / JarvisQuickAnalysisResponse) if needed
    if "api" not in sys.modules:
        sys.modules["api"] = types.ModuleType("api")
    if "api.models" not in sys.modules:
        from pydantic import BaseModel, ConfigDict, Field

        class JarvisQuickAnalysisRequest(BaseModel):
            model_config = ConfigDict(str_strip_whitespace=True)
            symbol: str = Field(default="SPY")
            period: str = Field(default="5d")

        class JarvisQuickAnalysisResponse(BaseModel):
            model_config = ConfigDict(frozen=True)
            symbol: str
            period: str
            analysis: str
            model: str
            generated_at: str

        fake_models = types.ModuleType("api.models")
        fake_models.JarvisQuickAnalysisRequest = JarvisQuickAnalysisRequest  # type: ignore[attr-defined]
        fake_models.JarvisQuickAnalysisResponse = JarvisQuickAnalysisResponse  # type: ignore[attr-defined]
        sys.modules["api.models"] = fake_models
        sys.modules["api"].models = fake_models  # type: ignore[attr-defined]

    # config.settings — just needs an API_KEY attr
    if "config" not in sys.modules:
        fake_config = types.ModuleType("config")

        class _Settings:
            API_KEY: str = "test-api-key-jarvis"

        fake_config.settings = _Settings()  # type: ignore[attr-defined]
        sys.modules["config"] = fake_config


_install_stubs()

# Now import the router under test
import routers.jarvis_router as jarvis_router_mod  # noqa: E402

# ── Minimal app fixture ───────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    """Build a minimal FastAPI app with only the jarvis router mounted."""
    app = FastAPI()
    app.include_router(jarvis_router_mod.router)
    return app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient for the minimal app; JSONL log redirected to tmp_path."""
    monkeypatch.setattr(jarvis_router_mod, "_ASK_LOG_PATH", tmp_path / "jarvis_ask.log")
    monkeypatch.setattr(jarvis_router_mod, "_LOG_DIR", tmp_path)
    return TestClient(_make_app())


# ── Test: health intent ───────────────────────────────────────────────────────


def test_ask_health(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """'is the engine healthy' routes to health handler and returns status info."""

    def fake_handle_health(question, context):
        return (
            "Engine status: OK. TradingView MCP: healthy. LLM path: healthy.",
            ["http://127.0.0.1:8010/health"],
            [],
        )

    monkeypatch.setattr(
        jarvis_router_mod,
        "_HANDLERS",
        {**jarvis_router_mod._HANDLERS, "health": fake_handle_health},
    )

    resp = client.post("/jarvis/ask", json={"question": "is the engine healthy"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "health"
    assert "Engine status" in data["answer"]
    assert "http://127.0.0.1:8010/health" in data["sources"]
    assert isinstance(data["elapsed_ms"], int)
    assert data["elapsed_ms"] >= 0


# ── Test: unknown intent ──────────────────────────────────────────────────────


def test_ask_unknown(client: TestClient) -> None:
    """Gibberish input routes to 'unknown' intent with a helpful listing."""
    resp = client.post(
        "/jarvis/ask",
        json={"question": "xyzzy frobnicate quux glorbnog"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "unknown"
    assert "I can answer about" in data["answer"]


def test_ask_unknown_question_lists_intents(client: TestClient) -> None:
    """Unknown intent response must list all 9 non-unknown supported intents."""
    resp = client.post(
        "/jarvis/ask",
        json={"question": "this is total nonsense qwerty 12345"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "unknown"
    answer = data["answer"]
    for intent in [
        "health",
        "bookmark_search",
        "bookmark_recent",
        "commentary",
        "briefing",
        "tearsheet",
        "regime",
        "pipeline_run",
        "position",
    ]:
        assert intent in answer, f"Expected '{intent}' in unknown-intent answer, got:\n{answer}"


# ── Test: safety refusal ──────────────────────────────────────────────────────


def test_ask_refused_overrides_safety(client: TestClient) -> None:
    """
    Safety-override attempts return HTTP 200 with intent='refused'.
    They must NOT return a 403/4xx — refusal is a normal answer, not an error.
    """
    dangerous_questions = [
        "override the kill switch",
        "disable safety layer now",
        "set live trading to true",
        "enable live trading",
        "bypass risk limits",
        "force trade on MES",
        "sell all positions",
        "buy all instruments",
        "override stop loss",
    ]
    for question in dangerous_questions:
        resp = client.post("/jarvis/ask", json={"question": question})
        assert resp.status_code == 200, f"Expected 200 for: {question!r}"
        data = resp.json()
        assert (
            data["intent"] == "refused"
        ), f"Expected intent='refused' for: {question!r}, got: {data['intent']!r}"
        assert "Refused" in data["answer"], f"Expected 'Refused' in answer for: {question!r}"
        assert (
            "safety_layer.py" in data["answer"]
        ), f"Expected safety_layer.py reference for: {question!r}"


# ── Test: bookmark_search intent ─────────────────────────────────────────────


def test_ask_bookmark_search(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """'search bookmarks for hermes' routes correctly and returns sources."""

    def fake_bookmark_search(question, context):
        return (
            "Found 2 bookmark(s) matching 'hermes':\n"
            "- Hermes Gateway Setup (#general)\n"
            "- Hermes WSL Config (#infra)",
            ["https://discord.com/bookmark/1", "https://discord.com/bookmark/2"],
            [],
        )

    monkeypatch.setattr(
        jarvis_router_mod,
        "_HANDLERS",
        {**jarvis_router_mod._HANDLERS, "bookmark_search": fake_bookmark_search},
    )

    resp = client.post(
        "/jarvis/ask",
        json={"question": "search bookmarks for hermes"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "bookmark_search"
    assert len(data["sources"]) == 2
    assert "hermes" in data["answer"].lower()


# ── Test: JSONL log metadata (no PII) ────────────────────────────────────────


def test_ask_logs_jsonl(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Each /jarvis/ask call writes exactly one JSONL line with metadata only.
    The question or answer text must NOT appear in the log.
    """
    log_file = tmp_path / "jarvis_ask.log"
    monkeypatch.setattr(jarvis_router_mod, "_ASK_LOG_PATH", log_file)
    monkeypatch.setattr(jarvis_router_mod, "_LOG_DIR", tmp_path)

    unique_question = "is the engine healthy xyzzy-unique-string-12345"

    # Stub the health handler so no real HTTP call is made
    def fake_health(question, context):
        return "Engine status: OK.", ["http://127.0.0.1:8010/health"], []

    monkeypatch.setattr(
        jarvis_router_mod,
        "_HANDLERS",
        {**jarvis_router_mod._HANDLERS, "health": fake_health},
    )

    resp = client.post("/jarvis/ask", json={"question": unique_question})
    assert resp.status_code == 200

    assert log_file.exists(), "JSONL log file was not created"
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1, "Expected at least one log entry"

    entry = json.loads(lines[-1])

    # Required metadata fields present
    assert "timestamp" in entry
    assert "intent" in entry
    assert "elapsed_ms" in entry
    assert "sources_count" in entry
    assert "actions_count" in entry

    # PII check: question text must NOT appear in the log
    log_text = log_file.read_text(encoding="utf-8")
    assert (
        "xyzzy-unique-string-12345" not in log_text
    ), "Question text leaked into the JSONL log — privacy violation"
    assert (
        "is the engine healthy" not in log_text
    ), "Question text leaked into the JSONL log — privacy violation"

    # Type checks
    assert isinstance(entry["elapsed_ms"], int)
    assert isinstance(entry["sources_count"], int)
    assert isinstance(entry["actions_count"], int)


# ── Test: pipeline_run pre-flight gate ───────────────────────────────────────


def test_pipeline_run_refused_when_kill_switch_active(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pipeline_run intent is refused when kill_switch_active=True."""

    def fake_fetch_health():
        return {"status": "ok", "kill_switch_active": True, "live_trading": False}

    monkeypatch.setattr(jarvis_router_mod, "_fetch_health_for_preflight", fake_fetch_health)

    resp = client.post("/jarvis/ask", json={"question": "run pipeline for MES"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "pipeline_run"
    assert "Refused" in data["answer"], f"Expected refusal in answer; got: {data['answer']!r}"
    assert "kill_switch_active=True" in data["answer"]


def test_pipeline_run_refused_when_engine_unhealthy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pipeline_run intent is refused when engine status != 'ok'."""

    def fake_fetch_health():
        return {"status": "degraded", "kill_switch_active": False, "live_trading": False}

    monkeypatch.setattr(jarvis_router_mod, "_fetch_health_for_preflight", fake_fetch_health)

    resp = client.post("/jarvis/ask", json={"question": "trigger pipeline for MNQ"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "pipeline_run"
    assert "Refused" in data["answer"], f"Expected refusal in answer; got: {data['answer']!r}"
    assert "status=degraded" in data["answer"]


def test_pipeline_run_proceeds_when_healthy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pipeline_run proceeds to the POST when pre-flight passes and POST is mocked."""

    def fake_fetch_health():
        return {"status": "ok", "kill_switch_active": False, "live_trading": False}

    monkeypatch.setattr(jarvis_router_mod, "_fetch_health_for_preflight", fake_fetch_health)

    # Stub the actual pipeline POST so no real HTTP call is made
    def fake_pipeline_run(question, context):
        return (
            "Pipeline run for MES complete. Decision: HOLD (confidence 55%).",
            ["http://127.0.0.1:8010/pipeline/run"],
            ["pipeline_run:MES:hold"],
        )

    monkeypatch.setattr(
        jarvis_router_mod,
        "_HANDLERS",
        {**jarvis_router_mod._HANDLERS, "pipeline_run": fake_pipeline_run},
    )

    resp = client.post("/jarvis/ask", json={"question": "run pipeline for MES"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "pipeline_run"
    # Should NOT be refused
    assert "Refused" not in data["answer"]
    assert "Pipeline run" in data["answer"]
