"""Tests for the read-only defined-risk options opportunity board."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from analysis.options_implied import build_symbol_block, parse_chain
from analysis.options_opportunity_board import build_opportunity_board

_NOW = datetime(2026, 7, 15, 13, 30, tzinfo=ZoneInfo("America/Chicago"))


def _opt(occ, bid, ask, iv, delta, oi=150, vol=40):
    return {
        "option": occ,
        "bid": bid,
        "ask": ask,
        "iv": iv,
        "delta": delta,
        "last_trade_price": (bid + ask) / 2,
        "open_interest": oi,
        "volume": vol,
    }


def _chain_fixture():
    near = "260715"
    return {
        "timestamp": "2026-07-15 18:20:00",
        "data": {
            "current_price": 628.42,
            "options": [
                _opt(f"SPY{near}C00620000", 8.50, 8.70, 0.14, 0.92),
                _opt(f"SPY{near}C00624000", 4.90, 5.10, 0.135, 0.78),
                _opt(f"SPY{near}C00626000", 3.10, 3.30, 0.133, 0.66),
                _opt(f"SPY{near}C00628000", 1.60, 1.70, 0.131, 0.52),
                _opt(f"SPY{near}C00630000", 0.70, 0.80, 0.130, 0.35),
                _opt(f"SPY{near}C00632000", 0.28, 0.34, 0.132, 0.20),
                _opt(f"SPY{near}C00634000", 0.10, 0.16, 0.134, 0.12),
                _opt(f"SPY{near}P00620000", 0.05, 0.07, 0.15, -0.05),
                _opt(f"SPY{near}P00624000", 0.22, 0.28, 0.14, -0.20),
                _opt(f"SPY{near}P00626000", 0.55, 0.65, 0.135, -0.33),
                _opt(f"SPY{near}P00628000", 1.30, 1.40, 0.129, -0.48),
                _opt(f"SPY{near}P00630000", 2.40, 2.60, 0.128, -0.64),
                _opt(f"SPY{near}P00632000", 4.00, 4.30, 0.131, -0.79),
            ],
        },
    }


class TestOptionsOpportunityBoard:
    def test_ranks_defined_risk_candidates_only(self):
        spot, _, contracts = parse_chain(_chain_fixture(), "SPY")
        board = build_opportunity_board("SPY", contracts, _NOW.date(), spot)

        assert board["status"] == "ok"
        assert board["candidates"]
        assert board["source"] == "CBOE delayed quotes"
        assert board["source_confidence"] > 0
        assert board["candidate_count"] >= 1
        assert all(c["max_loss"] > 0 for c in board["candidates"])
        assert all(c["max_gain"] > 0 for c in board["candidates"])
        assert all(len(c["legs"]) == 2 for c in board["candidates"])
        assert {leg["action"] for c in board["candidates"] for leg in c["legs"]} == {"BUY", "SELL"}
        assert all("NAKED" not in c["structure"] for c in board["candidates"])

    def test_bull_call_math_uses_conservative_bid_ask(self):
        spot, _, contracts = parse_chain(_chain_fixture(), "SPY")
        board = build_opportunity_board("SPY", contracts, _NOW.date(), spot)
        bull = next(
            c
            for c in board["candidates"] + board["rejected_candidates"]
            if c["structure"] == "BULL_CALL_DEBIT_SPREAD"
        )

        # Buy 628C ask 1.70, sell 634C bid 0.10 -> debit 1.60, width 6.
        assert bull["net_price"] == pytest.approx(1.60)
        assert bull["max_loss"] == pytest.approx(160.0)
        assert bull["max_gain"] == pytest.approx(440.0)
        assert bull["breakeven"] == pytest.approx(629.60)
        assert bull["pop"] is not None
        assert bull["ev_to_max_loss"] is not None
        assert bull["journal_url"] == "/journal?source=options-opportunity-board"
        assert "ANALYSIS_ONLY options review" in bull["journal_note"]

    def test_wide_quote_candidate_degrades_with_reject_reason(self):
        raw = _chain_fixture()
        for opt in raw["data"]["options"]:
            if opt["option"] == "SPY260715C00628000":
                opt["bid"], opt["ask"] = 0.50, 2.50
        spot, _, contracts = parse_chain(raw, "SPY")
        board = build_opportunity_board("SPY", contracts, _NOW.date(), spot)
        all_reasons = [
            reason
            for c in board["candidates"] + board["rejected_candidates"]
            for reason in c["reject_reasons"]
        ]
        assert any("wide bid/ask" in reason for reason in all_reasons)

    def test_symbol_block_embeds_nearest_opportunity_board(self):
        block = build_symbol_block("SPY", _chain_fixture(), _NOW)
        board = block["horizons"][0]["opportunity_board"]
        assert board["symbol"] == "SPY"
        assert board["expiry"] == "2026-07-15"
        assert board["candidates"]


class TestOpportunityBoardRouterProjection:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import routers.options_signals_router as osr

        monkeypatch.setattr(osr, "_DATA_DIR", tmp_path)
        app = FastAPI()
        app.include_router(osr.router)
        return TestClient(app), tmp_path

    def test_opportunity_board_endpoint_projects_latest_snapshot(self, client):
        tc, data_dir = client
        board = {"symbol": "SPY", "status": "ok", "candidates": [{"structure": "BULL_CALL_DEBIT_SPREAD"}]}
        payload = {
            "schema_version": 1,
            "generated_at": 123,
            "quote_ts": 120,
            "data_delayed_minutes": 15,
            "data_quality": "ok",
            "symbols": {"SPY": {"horizons": [{"label": "nearest", "opportunity_board": board}]}},
        }
        (data_dir / "latest.json").write_text(json.dumps(payload), encoding="utf-8")

        resp = tc.get("/options-signals/opportunity-board")
        assert resp.status_code == 200
        body = resp.json()
        assert body["boards"]["SPY"] == board
        assert "not a trade signal" in body["disclaimer"]
