"""Tests for ThinkScript generation and registry endpoints.

Uses FastAPI TestClient against the real router, mounted standalone (no
main.py auth middleware, matching this repo's other standalone router
tests e.g. test_hidden_pivots_router.py). External dependencies —
the injected technical analyst and the registry-loader functions — are
mocked via monkeypatch on the router module so each test controls its
own isolated state.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import thinkscript_router
from routers.thinkscript_router import router as ts_router
from schemas.thinkscript_registry import ScriptRegistry, ScriptRegistryEntry

# ─── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(ts_router)
    return TestClient(app)


def _fake_registry() -> ScriptRegistry:
    return ScriptRegistry(
        version=1,
        generated="2026-01-01",
        source_of_truth={"note": "test fixture"},
        duplicates_to_skip=[],
        scripts=[
            ScriptRegistryEntry(
                id="hp_ou_v1",
                file="hp_ou_v1.ts",
                docs="hp_ou_v1.md",
                author="jarvis",
                layer=1,
                layer_name="core",
                status="active",
                python_counterpart="analysis.hidden_pivots",
                panel="upper",
                jarvis_signals=["hp_ou"],
                tos_inputs={},
            )
        ],
    )


# ─── POST /thinkscript/generate ──────────────────────────────────────────


class TestGenerateEndpoint:
    def test_generate_without_technical_analyst_uses_template_fallback(self, monkeypatch, client):
        # No analyst injected -> llm_client is None -> generator falls back to
        # its deterministic template path (no network/LLM call).
        monkeypatch.setattr(thinkscript_router, "_technical_analyst", None)
        resp = client.post(
            "/thinkscript/generate",
            json={"symbol": "MCL", "timeframe": "15m", "is_futures": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "MCL"
        assert data["timeframe"] == "15m"
        assert isinstance(data["code"], str) and data["code"]
        assert isinstance(data["signals_included"], list)
        assert "timestamp" in data

    def test_generate_missing_symbol_returns_422(self, client):
        resp = client.post("/thinkscript/generate", json={"timeframe": "15m"})
        assert resp.status_code == 422

    def test_generate_swallows_technical_analyst_analyze_failure(self, monkeypatch, client):
        # Router wraps `_technical_analyst.analyze()` in a bare try/except that
        # swallows any exception and proceeds with tech_report=None -- verify
        # the endpoint still returns 200 rather than a 500 in that path.
        fake_analyst = MagicMock()
        fake_analyst.llm_client = None
        fake_analyst.analyze = AsyncMock(side_effect=RuntimeError("technical analysis boom"))
        monkeypatch.setattr(thinkscript_router, "_technical_analyst", fake_analyst)

        resp = client.post(
            "/thinkscript/generate",
            json={"symbol": "SPY", "timeframe": "5m"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "SPY"
        fake_analyst.analyze.assert_awaited_once()


# ─── GET /thinkscript/registry ───────────────────────────────────────────


class TestRegistryEndpoint:
    def test_returns_full_catalog(self, monkeypatch, client):
        monkeypatch.setattr(thinkscript_router, "load_registry", lambda: _fake_registry())
        resp = client.get("/thinkscript/registry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == 1
        assert len(data["scripts"]) == 1
        assert data["scripts"][0]["id"] == "hp_ou_v1"

    def test_returns_503_when_registry_file_missing(self, monkeypatch, client):
        def _raise():
            raise FileNotFoundError("registry.yaml not found")

        monkeypatch.setattr(thinkscript_router, "load_registry", _raise)
        resp = client.get("/thinkscript/registry")
        assert resp.status_code == 503


# ─── GET /thinkscript/registry/{script_id} ───────────────────────────────


class TestRegistryEntryEndpoint:
    def test_returns_entry_with_doc_markdown(self, monkeypatch, client):
        monkeypatch.setattr(thinkscript_router, "load_registry", lambda: _fake_registry())
        monkeypatch.setattr(thinkscript_router, "read_doc", lambda path: "# HP OU v1\nDocs body.")

        resp = client.get("/thinkscript/registry/hp_ou_v1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entry"]["id"] == "hp_ou_v1"
        assert data["doc_markdown"] == "# HP OU v1\nDocs body."

    def test_returns_404_for_unknown_script_id(self, monkeypatch, client):
        monkeypatch.setattr(thinkscript_router, "load_registry", lambda: _fake_registry())
        resp = client.get("/thinkscript/registry/does-not-exist")
        assert resp.status_code == 404

    def test_returns_503_when_registry_file_missing(self, monkeypatch, client):
        def _raise():
            raise FileNotFoundError("registry.yaml not found")

        monkeypatch.setattr(thinkscript_router, "load_registry", _raise)
        resp = client.get("/thinkscript/registry/hp_ou_v1")
        assert resp.status_code == 503
