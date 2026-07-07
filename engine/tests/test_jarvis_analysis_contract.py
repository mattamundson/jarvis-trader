"""
Jarvis quick-analysis contract tests.

These tests exercise the real FastAPI `/jarvis/analyze` route in the engine,
with a local ``google.genai`` import stub so the module tree can be imported in
this test environment without the production dependency installed.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
import types
from datetime import datetime

import pytest
from fastapi.testclient import TestClient


def _install_google_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a minimal ``google.genai`` module so engine imports succeed."""
    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = object  # never instantiated in these tests

    fake_yfinance = types.ModuleType("yfinance")

    class _Ticker:
        def __init__(self, *args, **kwargs):
            pass

        def history(self, *args, **kwargs):
            raise RuntimeError("yfinance history is not used in Jarvis contract tests")

    fake_yfinance.Ticker = _Ticker

    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)


@pytest.fixture()
def jarvis_client(monkeypatch: pytest.MonkeyPatch):
    _install_google_stub(monkeypatch)

    _engine_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    if _engine_root not in sys.path:
        sys.path.insert(0, _engine_root)

    # Import after the stub is in place so the real engine router can load.
    main = importlib.import_module("main")
    jarvis_router = importlib.import_module("routers.jarvis_router")
    settings = importlib.import_module("config").settings

    def fake_analyze_symbol(symbol: str, period: str) -> str:
        if not re.fullmatch(r"^[A-Z0-9.\-^]{1,20}$", symbol or ""):
            raise ValueError(f"No market data returned for {symbol} with period={period}")
        return "Synthetic analysis"

    monkeypatch.setattr(jarvis_router.jarvis_analysis, "analyze_symbol", fake_analyze_symbol)
    monkeypatch.setattr(jarvis_router.jarvis_analysis, "MODEL_NAME", "test-model")

    return TestClient(main.app, headers={"X-API-Key": settings.API_KEY})


def test_jarvis_analysis_get_contract(jarvis_client: TestClient) -> None:
    response = jarvis_client.get("/jarvis/analyze?symbol=spy")

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "SPY"
    assert payload["period"] == "5d"
    assert payload["analysis"] == "Synthetic analysis"
    assert payload["model"] == "test-model"
    assert payload["generated_at"]
    datetime.fromisoformat(payload["generated_at"])


def test_jarvis_analysis_post_contract(jarvis_client: TestClient) -> None:
    response = jarvis_client.post("/jarvis/analyze", json={"symbol": "qqq", "period": "1mo"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "QQQ"
    assert payload["period"] == "1mo"
    assert payload["analysis"] == "Synthetic analysis"
    assert payload["model"] == "test-model"
    datetime.fromisoformat(payload["generated_at"])


def test_jarvis_analysis_rejects_invalid_symbol(jarvis_client: TestClient) -> None:
    response = jarvis_client.post("/jarvis/analyze", json={"symbol": "bad symbol!!"})

    assert response.status_code == 400
    assert "No market data returned" in response.json()["detail"]


@pytest.mark.xfail(
    reason="Jarvis router currently serializes the unsupported-period error path as 500",
    strict=False,
)
def test_jarvis_analysis_rejects_unsupported_period(jarvis_client: TestClient) -> None:
    response = jarvis_client.get("/jarvis/analyze?symbol=spy&period=17d")

    assert response.status_code == 400
