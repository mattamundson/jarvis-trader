"""Tests for the read-only A-01 runtime truth snapshot tool."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "phase0_runtime_truth_snapshot.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("_phase0_runtime_truth_snapshot", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_engine_url_is_loopback_only():
    script = _load_script()

    assert script._validate_engine_url("http://127.0.0.1:8010") == "http://127.0.0.1:8010"
    assert script._validate_engine_url("http://localhost:8010/") == "http://127.0.0.1:8010"
    assert script._validate_engine_url("https://[::1]:8010") == "https://[::1]:8010"

    for unsafe in (
        "https://example.com:8010",
        "http://user:password@127.0.0.1:8010",
        "http://127.0.0.1:8010/config/overview",
        "http://127.0.0.1:8010?redirect=https://example.com",
    ):
        with pytest.raises(ValueError):
            script._validate_engine_url(unsafe)


def test_get_json_uses_proxy_free_non_redirecting_get(monkeypatch):
    script = _load_script()
    observed = {}

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return b'{"status":"ok"}'

    class _Opener:
        @staticmethod
        def open(request, timeout):
            observed["method"] = request.get_method()
            observed["url"] = request.full_url
            observed["api_key"] = request.headers.get("X-api-key")
            observed["timeout"] = timeout
            return _Response()

    def fake_build_opener(*handlers):
        observed["handlers"] = handlers
        return _Opener()

    monkeypatch.setattr(script.urllib.request, "build_opener", fake_build_opener)
    result = script._get_json("http://127.0.0.1:8010", "/health", "synthetic-secret", 1.25)

    assert result["body"] == {"status": "ok"}
    assert observed["method"] == "GET"
    assert observed["url"] == "http://127.0.0.1:8010/health"
    assert observed["api_key"] == "synthetic-secret"
    assert observed["timeout"] == 1.25
    assert any(
        isinstance(handler, script.urllib.request.ProxyHandler) and handler.proxies == {}
        for handler in observed["handlers"]
    )
    assert any(isinstance(handler, script._RejectRedirects) for handler in observed["handlers"])
    with pytest.raises(ValueError):
        script._get_json("http://127.0.0.1:8010", "/safety/kill-switch", None, 1.0)


def test_sanitizers_drop_secrets_accounts_paths_and_free_text():
    script = _load_script()
    config = {
        "categories": {
            "safety": [
                {"key": "MAX_DAILY_LOSS_PCT", "value": 0.06},
                {"key": "LIVE_TRADING_ENABLED", "value": False},
            ],
            "broker": [
                {"key": "IB_ACCOUNT_ID", "value": "SYNTHETIC-ACCOUNT"},
                {"key": "DB_PATH", "value": "C:/Users/example/private.db"},
            ],
            "llm": [
                {"key": "API_KEY", "value": "synthetic-secret"},
                {"key": "JARVIS_LLM_PROVIDER", "value": " OLLAMA "},
            ],
        }
    }

    assert script._flatten_config(config) == {
        "JARVIS_LLM_PROVIDER": "ollama",
        "LIVE_TRADING_ENABLED": False,
        "MAX_DAILY_LOSS_PCT": 0.06,
    }
    assert script._sanitize_health(
        {
            "overall": "degraded",
            "subsystems": {
                "ib_gateway": {"status": "unhealthy", "account": "SYNTHETIC-ACCOUNT"}
            },
            "status": "healthy",
            "source": "ibkr",
            "kill_switch_active": True,
            "daily_pnl_pct": -0.01,
            "account": "SYNTHETIC-ACCOUNT",
            "detail": "contains private operator text",
            "database": {"source": "sqlite", "path": "C:/Users/example/private.db"},
        }
    ) == {
        "overall": "degraded",
        "subsystems": {"ib_gateway": {"status": "unhealthy"}},
        "status": "healthy",
        "source": "ibkr",
        "kill_switch_active": True,
        "daily_pnl_pct": -0.01,
        "database": {"source": "sqlite"},
    }


def test_eligibility_uses_canonical_trading_status_schema():
    script = _load_script()

    result = script._safe_endpoint_result(
        {
            "reachable": True,
            "http_status": 200,
            "json": True,
            "body": {
                "summary": {"total": 2, "tradeable": 1, "enabled": 1, "disagreements": 0},
                "symbols": [
                    {
                        "symbol": "MES",
                        "enabled": True,
                        "authorized": True,
                        "tradeable": True,
                        "config_agrees": True,
                        "verdict": "PASS",
                        "verdict_age_days": 1.5,
                        "disagreements": ["free text is intentionally dropped"],
                    }
                ],
            },
        },
        "eligibility",
    )

    assert result["summary"] == {
        "total": 2,
        "tradeable": 1,
        "enabled": 1,
        "disagreements": 0,
    }
    assert result["symbols"] == [
        {
            "symbol": "MES",
            "enabled": True,
            "authorized": True,
            "tradeable": True,
            "config_agrees": True,
            "verdict": "PASS",
            "verdict_age_days": 1.5,
        }
    ]


def test_build_snapshot_never_serializes_api_key(monkeypatch):
    script = _load_script()
    monkeypatch.setattr(script, "_api_key", lambda: "synthetic-secret")
    monkeypatch.setattr(script, "_git", lambda *_args: "")
    monkeypatch.setattr(script, "_port_open", lambda *_args, **_kwargs: False)

    def fake_get(_base_url, path, api_key, _timeout):
        assert api_key == "synthetic-secret"
        if path == "/config/overview":
            return {
                "reachable": True,
                "http_status": 200,
                "json": True,
                "body": {
                    "categories": {
                        "safety": [{"key": "MAX_DRAWDOWN_PCT", "value": 0.20}],
                        "other": [{"key": "API_KEY", "value": "***cret"}],
                    }
                },
            }
        return {
            "reachable": True,
            "http_status": 200,
            "json": True,
            "body": {"status": "ok", "account": "SYNTHETIC-ACCOUNT"},
        }

    monkeypatch.setattr(script, "_get_json", fake_get)
    snapshot = script.build_snapshot("http://127.0.0.1:8010", 1.0)
    encoded = json.dumps(snapshot)

    assert "synthetic-secret" not in encoded
    assert "SYNTHETIC-ACCOUNT" not in encoded
    assert snapshot["api_key_available_for_probe"] is True
    assert snapshot["api"]["config_overview"]["safe_config"] == {"MAX_DRAWDOWN_PCT": 0.20}


def test_main_refuses_overwrite_without_force(tmp_path, monkeypatch):
    script = _load_script()
    output = tmp_path / "snapshot.json"
    snapshot = {
        "api": {
            "health": {"reachable": False},
            "config_overview": {"reachable": False},
        },
        "ports": {"ib_paper_4002_open": False},
    }
    monkeypatch.setattr(script, "build_snapshot", lambda *_args: snapshot)

    assert script.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == snapshot

    with pytest.raises(SystemExit) as exc_info:
        script.main(["--output", str(output)])
    assert exc_info.value.code == 2

    changed = dict(snapshot, schema_version=2)
    monkeypatch.setattr(script, "build_snapshot", lambda *_args: changed)
    assert script.main(["--output", str(output), "--force"]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == 2


def test_script_is_stdlib_only_and_has_no_engine_imports():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "from engine" not in source
    assert "import engine" not in source
    assert "method=\"POST\"" not in source
    assert "method=\"PUT\"" not in source
    assert "method=\"DELETE\"" not in source
