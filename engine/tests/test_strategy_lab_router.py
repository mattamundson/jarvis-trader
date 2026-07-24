"""
Tests for engine/routers/strategy_lab_router.py

Covered:
  - POST /strategy-lab/run       — success (defaults), success (custom params passed
                                    through to the background task), 422 on bad input
  - GET  /strategy-lab/results   — success (aggregates real JSON/JSONL files),
                                    no-files-yet edge, malformed-line-skipped edge

Design:
  - Minimal FastAPI app wrapping only strategy_lab_router (no full main.py import).
  - `/run`'s only external dependency is `strategy_lab.strategy_loop.run_strategy_loop`,
    which is mocked so no LLM/backtest work actually executes; FastAPI's
    BackgroundTasks runs synchronously within the TestClient request/response cycle,
    so the mock's call is asserted directly.
  - `/results` reads real files via relative `Path("backtest/results/...")`, so tests
    `monkeypatch.chdir(tmp_path)` and write real JSON/JSONL fixtures — this exercises
    the router's actual aggregation/parsing logic rather than mocking it away.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------

_ENGINE_ROOT = str(Path(__file__).parent.parent)
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from routers.strategy_lab_router import router as strategy_lab_router  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(strategy_lab_router)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# POST /strategy-lab/run
# ---------------------------------------------------------------------------


def test_start_strategy_lab_defaults(client):
    mock_run_loop = MagicMock()
    with patch("strategy_lab.strategy_loop.run_strategy_loop", mock_run_loop):
        resp = client.post("/strategy-lab/run")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "started"
    assert data["symbol"] == "MES"
    assert data["max_iterations"] == 20
    assert "MES" in data["message"]
    mock_run_loop.assert_called_once_with(
        symbol="MES", max_iterations=20, start="2024-06-01", end="2026-03-27"
    )


def test_start_strategy_lab_custom_params_pass_through(client):
    mock_run_loop = MagicMock()
    with patch("strategy_lab.strategy_loop.run_strategy_loop", mock_run_loop):
        resp = client.post(
            "/strategy-lab/run",
            params={
                "symbol": "MGC",
                "max_iterations": 5,
                "start": "2025-01-01",
                "end": "2025-06-01",
            },
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["symbol"] == "MGC"
    assert data["max_iterations"] == 5
    mock_run_loop.assert_called_once_with(
        symbol="MGC", max_iterations=5, start="2025-01-01", end="2025-06-01"
    )


def test_start_strategy_lab_bad_max_iterations_type_422(client):
    """max_iterations is typed int — a non-numeric value must fail FastAPI validation,
    never reach run_strategy_loop."""
    mock_run_loop = MagicMock()
    with patch("strategy_lab.strategy_loop.run_strategy_loop", mock_run_loop):
        resp = client.post("/strategy-lab/run", params={"max_iterations": "not-a-number"})
    assert resp.status_code == 422
    mock_run_loop.assert_not_called()


# ---------------------------------------------------------------------------
# GET /strategy-lab/results
# ---------------------------------------------------------------------------


def test_results_no_files_yet(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    resp = client.get("/strategy-lab/results")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["best_strategies"] == []
    assert data["stats"] == {"total_evaluated": 0, "eligible_count": 0, "best_pf": 0}
    assert "No results yet" in data["message"]


def test_results_success_with_data(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    results_dir = tmp_path / "backtest" / "results"
    results_dir.mkdir(parents=True)

    best = [
        {"name": "strat_a", "metrics": {"profit_factor": 1.8}},
        {"name": "strat_b", "metrics": {"pf": 2.1}},
    ]
    (results_dir / "strategy_lab_best.json").write_text(json.dumps(best))

    jsonl_lines = [
        json.dumps({"name": "strat_a", "verdict": "ELIGIBLE"}),
        json.dumps({"name": "strat_c", "verdict": "REJECTED"}),
        json.dumps({"name": "strat_b", "verdict": "ELIGIBLE"}),
    ]
    (results_dir / "strategy_lab_results.jsonl").write_text("\n".join(jsonl_lines) + "\n")

    resp = client.get("/strategy-lab/results")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["best_strategies"] == best
    assert data["stats"]["total_evaluated"] == 3
    assert data["stats"]["eligible_count"] == 2
    assert data["stats"]["best_pf"] == 2.1
    assert "Top 2 strategies shown" in data["message"]


def test_results_skips_malformed_jsonl_line(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    results_dir = tmp_path / "backtest" / "results"
    results_dir.mkdir(parents=True)

    (results_dir / "strategy_lab_best.json").write_text("[]")
    jsonl_lines = [
        json.dumps({"name": "strat_a", "verdict": "ELIGIBLE"}),
        "{not valid json,,,",
        json.dumps({"name": "strat_b", "verdict": "REJECTED"}),
    ]
    (results_dir / "strategy_lab_results.jsonl").write_text("\n".join(jsonl_lines) + "\n")

    resp = client.get("/strategy-lab/results")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Malformed line silently skipped — only the 2 valid lines counted.
    assert data["stats"]["total_evaluated"] == 2
    assert data["stats"]["eligible_count"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
