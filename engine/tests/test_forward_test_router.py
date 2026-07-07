"""US-003 tests — GET /forward-test/status thin reader.

The endpoint recomputes nothing: it reads the two existing writers via
_query_paper_trade_stats() (paper trades JSONL) and find_verdict() (gate-v2
verdict files), judges with the canonical live_readiness thresholds, and reports
an as-of timestamp + staleness. Missing data => explicit "not_run".

The route function late-imports both readers, so patching them at their source
modules is picked up at call time.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from routers import forward_test_router
from routers.forward_test_router import get_forward_test_status


def _stats(**over):
    base = {
        "n_closed": 0,
        "n_open": 0,
        "first_entry": None,
        "last_entry": None,
        "days_elapsed": None,
        "forward_pf": None,
        "total_pnl": 0.0,
        "available": False,
    }
    base.update(over)
    return base


def _patch(monkeypatch, stats, verdict):
    monkeypatch.setattr(
        "backtest.live_readiness._query_paper_trade_stats", lambda symbol: stats
    )
    monkeypatch.setattr(
        "routers.strategy_ledger_router.find_verdict",
        lambda symbol, family=None: verdict,
    )


def test_not_run_when_no_paper_and_no_verdict(monkeypatch):
    _patch(monkeypatch, _stats(available=False), None)
    out = get_forward_test_status(symbol="mes")
    assert out.symbol == "MES"
    assert out.status == "not_run"
    assert out.as_of is None
    assert out.gate_verdict is None
    assert "no gate verdict" in out.detail.lower()


def test_not_run_carries_verdict_asof_when_paper_not_started(monkeypatch):
    created = (datetime.now(tz=timezone.utc) - timedelta(days=5)).isoformat()
    _patch(
        monkeypatch,
        _stats(available=True, n_closed=0, n_open=0),
        {"verdict": "PASS", "family": "trend", "created_at": created, "rank": 1},
    )
    out = get_forward_test_status(symbol="MES")
    assert out.status == "not_run"
    assert out.gate_verdict == "PASS"
    assert out.gate_family == "trend"
    assert out.as_of is not None  # from the verdict created_at
    assert out.as_of_age_days == 5
    assert out.stale is False


def test_in_progress_below_thresholds(monkeypatch):
    _patch(
        monkeypatch,
        _stats(available=True, n_closed=10, n_open=1, days_elapsed=6, forward_pf=2.0),
        None,
    )
    out = get_forward_test_status(symbol="MES")
    assert out.status == "in_progress"
    assert out.n_closed == 10
    assert "10/30" in out.detail


def test_pass_when_thresholds_met_and_pf_ok(monkeypatch):
    last = datetime.now(tz=timezone.utc) - timedelta(hours=2)
    _patch(
        monkeypatch,
        _stats(
            available=True, n_closed=35, n_open=0, days_elapsed=40,
            forward_pf=1.5, total_pnl=1234.5, last_entry=last,
        ),
        {"verdict": "PASS", "family": "trend",
         "created_at": (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()},
    )
    out = get_forward_test_status(symbol="MES")
    assert out.status == "pass"
    assert out.forward_pf == 1.5
    assert out.forward_pf_infinite is False
    assert out.total_pnl == 1234.5
    assert out.stale is False


def test_fail_when_pf_below_min(monkeypatch):
    _patch(
        monkeypatch,
        _stats(available=True, n_closed=35, n_open=0, days_elapsed=40, forward_pf=0.8),
        None,
    )
    out = get_forward_test_status(symbol="MES")
    assert out.status == "fail"
    assert out.forward_pf == 0.8


def test_infinite_pf_is_json_safe_and_passes(monkeypatch):
    _patch(
        monkeypatch,
        _stats(
            available=True, n_closed=40, n_open=0, days_elapsed=45,
            forward_pf=float("inf"),
        ),
        None,
    )
    out = get_forward_test_status(symbol="MES")
    assert out.status == "pass"
    assert out.forward_pf_infinite is True
    assert out.forward_pf is None  # sanitized — no Infinity in the payload
    dumped = out.model_dump()
    assert dumped["forward_pf"] is None
    # round-trips through strict JSON without raising on Infinity
    import json
    json.dumps(dumped, allow_nan=False)


def test_stale_when_asof_older_than_ttl(monkeypatch):
    old = (datetime.now(tz=timezone.utc) - timedelta(days=60)).isoformat()
    _patch(
        monkeypatch,
        _stats(available=True, n_closed=35, n_open=0, days_elapsed=40, forward_pf=1.2),
        {"verdict": "PASS", "family": "trend", "created_at": old},
    )
    out = get_forward_test_status(symbol="MES")
    assert out.as_of_age_days >= 59
    assert out.stale is True


def test_defensive_when_reader_raises(monkeypatch):
    def _boom(symbol):
        raise RuntimeError("corrupt JSONL")

    monkeypatch.setattr("backtest.live_readiness._query_paper_trade_stats", _boom)
    monkeypatch.setattr(
        "routers.strategy_ledger_router.find_verdict", lambda symbol, family=None: None
    )
    out = get_forward_test_status(symbol="MES")
    # Bad store must not 500 — degrade to not_run.
    assert out.status == "not_run"


def test_thresholds_provenance_present(monkeypatch):
    _patch(monkeypatch, _stats(available=False), None)
    out = get_forward_test_status(symbol="MES")
    assert out.thresholds["min_trades"] == 30
    assert out.thresholds["min_days"] == 30
    assert out.thresholds["min_pf"] == 1.0
    assert out.thresholds["verdict_ttl_days"] == 30


def test_route_registered_on_app():
    # Real wiring check: the router is imported + included in the FastAPI app.
    # Local import keeps the heavy app construction out of the fast unit tests.
    from main import app

    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/forward-test/status" in paths


# ── attribution fix: surface the verdict for the LIVE-TRADED strategy ────────
# Bug: find_verdict(symbol) with no family returned the best-RANKED PASS, so MGC
# surfaced trend_rv_filter (rank1) even though the engine trades plain trend
# (rank4). _live_gate_family resolves the family actually routed live from
# paper_config so the surfaced verdict matches what is being traded.


def test_live_gate_family_resolves_traded_strategy():
    # Resolves the family from each symbol's LIVE paper_config, so the two
    # symbols map differently — that distinction is the whole point of the fix.
    # MGC trades plain sma_trend (no RV filter in its sma_params) -> "trend".
    assert forward_test_router._live_gate_family("MGC") == "trend"
    # MES config carries min_rv_annualized=9.0 -> "trend_rv_filter".
    assert forward_test_router._live_gate_family("MES") == "trend_rv_filter"
    # Unknown / unconfigured symbol -> None (preserves find_verdict's default).
    assert forward_test_router._live_gate_family("ZZZZ") is None


def test_live_gate_family_tracks_rv_filter_when_live(monkeypatch):
    # Forward-compatible: if live MGC is switched to the RV-filter variant, the
    # resolver tracks it automatically (attribution stays correct).
    monkeypatch.setattr(
        "backtest.paper_config.PAPER_CONFIGS",
        {"MGC": {"strategy": "sma_trend",
                 "sma_params": {"fast": 50, "slow": 120, "atr_trail_mult": 2.0,
                                "min_rv_annualized": 9.0}}},
    )
    assert forward_test_router._live_gate_family("MGC") == "trend_rv_filter"


def test_mgc_surfaces_live_traded_family_not_best_verdict(monkeypatch):
    # Regression for the attribution mismatch: the router must ask find_verdict
    # for the LIVE-traded family ("trend"), not let it default to the best-ranked
    # PASS ("trend_rv_filter").
    captured: dict = {}

    def _spy_find_verdict(symbol, family=None):
        captured["family"] = family
        return {"verdict": "PASS", "family": family,
                "created_at": datetime.now(tz=timezone.utc).isoformat(), "rank": 4}

    monkeypatch.setattr(
        "backtest.live_readiness._query_paper_trade_stats",
        lambda symbol: _stats(available=False),
    )
    monkeypatch.setattr(
        "routers.strategy_ledger_router.find_verdict", _spy_find_verdict
    )
    out = get_forward_test_status(symbol="MGC")
    assert captured["family"] == "trend"
    assert out.gate_family == "trend"
