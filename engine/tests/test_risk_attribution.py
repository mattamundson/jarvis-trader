"""
Tests for engine/analytics/risk_attribution.py

All tests are fully offline — they use in-memory SQLite databases.
No engine startup, no external I/O, no LLM calls.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_db(rows: list[dict]) -> str:
    """
    Create a temp SQLite DB matching the paper_trades schema with given rows.
    Returns the file path (caller is responsible for cleanup if needed).
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute(
        """
        CREATE TABLE paper_trades (
            id         INTEGER PRIMARY KEY,
            trade_id   TEXT NOT NULL,
            symbol     TEXT NOT NULL,
            side       TEXT NOT NULL,
            quantity   REAL NOT NULL,
            entry_price REAL NOT NULL,
            exit_price  REAL,
            entry_time  TEXT NOT NULL,
            exit_time   TEXT,
            pnl         REAL,
            status      TEXT NOT NULL DEFAULT 'open',
            strategy_params TEXT,
            notes       TEXT DEFAULT '',
            account_id  TEXT NOT NULL DEFAULT 'A'
        )
        """
    )
    for i, row in enumerate(rows):
        conn.execute(
            """
            INSERT INTO paper_trades
              (trade_id, symbol, side, quantity, entry_price, exit_price,
               entry_time, exit_time, pnl, status, strategy_params, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("trade_id", f"t-{i}"),
                row.get("symbol", "MES"),
                row.get("side", "buy"),
                row.get("quantity", 1),
                row.get("entry_price", 5000.0),
                row.get("exit_price", 5010.0),
                row.get("entry_time", "2026-05-11T10:00:00+00:00"),
                row.get("exit_time", "2026-05-11T14:00:00+00:00"),
                row.get("pnl", 50.0),
                row.get("status", "closed"),
                row.get("strategy_params"),
                row.get("account_id", "A"),
            ),
        )
    conn.commit()
    conn.close()
    return tmp.name


def _signals_json(**kwargs) -> str:
    """Build strategy_params JSON with analyst_signals."""
    return json.dumps({"source": "pipeline", "analyst_signals": kwargs})


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestAttributeEmptyDay:
    def test_attribute_empty_day_returns_zeros(self) -> None:
        """No trades for the date → all zeros, top_contributor=None, residual=0."""
        from analytics.risk_attribution import ANALYST_SLOTS, attribute_daily_pnl

        db = _make_db([])  # empty table
        result = attribute_daily_pnl(date(2026, 5, 20), db_path=db)

        assert result.n_trades == 0
        assert result.total_pnl == 0.0
        assert result.top_contributor is None
        assert result.residual == 0.0
        assert result.attributed_trade_count == 0
        assert result.unattributed_trade_count == 0
        for slot in ANALYST_SLOTS:
            assert result.attribution[slot] == 0.0


class TestSingleTradeFullCredit:
    def test_single_analyst_gets_full_credit(self) -> None:
        """One analyst with non-zero signal → 100% of P&L attributed to that analyst."""
        from analytics.risk_attribution import attribute_daily_pnl

        params = _signals_json(technical=0.8, news=0.0, social=0.0, fundamental=0.0, corey=0.0)
        db = _make_db(
            [
                {
                    "pnl": 200.0,
                    "status": "closed",
                    "exit_time": "2026-05-11T15:00:00+00:00",
                    "strategy_params": params,
                }
            ]
        )
        result = attribute_daily_pnl(date(2026, 5, 11), db_path=db)

        assert result.n_trades == 1
        assert result.total_pnl == 200.0
        # technical had the only non-zero signal → 100% credit
        assert abs(result.attribution["technical"] - 200.0) < 0.01
        assert result.top_contributor == "technical"
        # All other analysts should be zero
        for slot in ["news", "social", "fundamental", "corey"]:
            assert result.attribution[slot] == 0.0
        # residual should be near-zero (just floating point)
        assert abs(result.residual) < 0.01
        assert result.attributed_trade_count == 1
        assert result.unattributed_trade_count == 0


class TestMultiAnalystProRata:
    def test_pro_rata_split(self) -> None:
        """
        Three analysts signal equally → each gets 1/3 of P&L.
        technical=0.6, news=0.3, corey=0.3 → abs_total=1.2
        weights: technical=0.5, news=0.25, corey=0.25
        P&L=400 → technical=200, news=100, corey=100
        """
        from analytics.risk_attribution import attribute_daily_pnl

        params = _signals_json(technical=0.6, news=0.3, corey=0.3)
        db = _make_db(
            [
                {
                    "pnl": 400.0,
                    "status": "closed",
                    "exit_time": "2026-05-11T15:00:00+00:00",
                    "strategy_params": params,
                }
            ]
        )
        result = attribute_daily_pnl(date(2026, 5, 11), db_path=db)

        assert abs(result.attribution["technical"] - 200.0) < 0.01
        assert abs(result.attribution["news"] - 100.0) < 0.01
        assert abs(result.attribution["corey"] - 100.0) < 0.01
        assert result.top_contributor == "technical"
        assert abs(result.residual) < 0.01

    def test_negative_signal_gets_negative_weight(self) -> None:
        """
        Opposing signals: bullish technical vs bearish news on a losing trade.

        technical=0.5 (bullish), news=-0.5 (bearish) → abs_total=1.0
        weights: technical=+0.5, news=-0.5
        P&L=-100 → technical=-50 (drove the bad trade), news=+50 (was right)

        Residual = 0 because a verdict exists — opposing signals are fully represented
        as positive/negative contributions, not absorbed into residual.
        """
        from analytics.risk_attribution import attribute_daily_pnl

        params = _signals_json(technical=0.5, news=-0.5)
        db = _make_db(
            [
                {
                    "pnl": -100.0,
                    "status": "closed",
                    "exit_time": "2026-05-08T15:00:00+00:00",
                    "strategy_params": params,
                }
            ]
        )
        result = attribute_daily_pnl(date(2026, 5, 8), db_path=db)

        assert abs(result.attribution["technical"] - (-50.0)) < 0.01
        assert abs(result.attribution["news"] - 50.0) < 0.01
        # Residual = 0: a verdict exists, so trade is fully "attributed"
        # (the opposing signals explain the mixed outcome)
        assert result.residual == 0.0
        assert result.attributed_trade_count == 1
        assert result.unattributed_trade_count == 0


class TestResidualCapturesUnexplainedPnL:
    def test_no_verdict_goes_to_residual(self) -> None:
        """Trade with no strategy_params → full P&L lands in residual."""
        from analytics.risk_attribution import ANALYST_SLOTS, attribute_daily_pnl

        db = _make_db(
            [
                {
                    "pnl": 300.0,
                    "status": "closed",
                    "exit_time": "2026-05-11T15:00:00+00:00",
                    "strategy_params": None,
                }
            ]
        )
        result = attribute_daily_pnl(date(2026, 5, 11), db_path=db)

        # All analyst contributions zero
        for slot in ANALYST_SLOTS:
            assert result.attribution[slot] == 0.0
        # Residual = total_pnl
        assert abs(result.residual - 300.0) < 0.01
        assert result.unattributed_trade_count == 1
        assert result.attributed_trade_count == 0

    def test_mixed_day_residual_accumulates(self) -> None:
        """
        One trade with verdict + one without.
        Residual = pnl of the unattributed trade only.
        """
        from analytics.risk_attribution import attribute_daily_pnl

        params = _signals_json(technical=1.0)
        db = _make_db(
            [
                {
                    "pnl": 100.0,
                    "status": "closed",
                    "exit_time": "2026-05-11T10:00:00+00:00",
                    "strategy_params": params,
                },
                {
                    "pnl": 50.0,
                    "status": "closed",
                    "exit_time": "2026-05-11T11:00:00+00:00",
                    "strategy_params": None,  # no verdict → goes to residual
                },
            ]
        )
        result = attribute_daily_pnl(date(2026, 5, 11), db_path=db)

        assert result.total_pnl == 150.0
        # Technical gets full credit for the attributed trade (100%)
        assert abs(result.attribution["technical"] - 100.0) < 0.01
        # Unattributed trade goes entirely to residual
        assert abs(result.residual - 50.0) < 0.01
        assert result.attributed_trade_count == 1
        assert result.unattributed_trade_count == 1


class TestWindowAggregation:
    def test_multi_day_rollup(self) -> None:
        """Two trading days → window sums correctly and top_contributor is deterministic."""
        from analytics.risk_attribution import attribute_window

        params_day1 = _signals_json(technical=1.0)  # 100% technical
        params_day2 = _signals_json(corey=1.0)  # 100% corey

        db = _make_db(
            [
                {
                    "pnl": 100.0,
                    "status": "closed",
                    "exit_time": "2026-05-11T15:00:00+00:00",
                    "strategy_params": params_day1,
                },
                {
                    "pnl": 200.0,
                    "status": "closed",
                    "exit_time": "2026-05-08T15:00:00+00:00",
                    "strategy_params": params_day2,
                },
            ]
        )

        window = attribute_window(date(2026, 5, 8), date(2026, 5, 11), db_path=db)

        assert window.n_trades == 2
        assert window.total_pnl == 300.0
        assert window.days_with_trades == 2

        # Corey had more absolute total (200 vs 100) → top contributor
        assert window.top_contributor_by_abs == "corey"
        # Technical total = 100, corey total = 200
        assert abs(window.per_analyst["technical"]["total"] - 100.0) < 0.01
        assert abs(window.per_analyst["corey"]["total"] - 200.0) < 0.01

    def test_empty_window_returns_zeros(self) -> None:
        """No trades in window → all totals zero, top_contributor is a slot name."""
        from analytics.risk_attribution import attribute_window

        db = _make_db([])
        window = attribute_window(date(2026, 5, 1), date(2026, 5, 7), db_path=db)

        assert window.n_trades == 0
        assert window.total_pnl == 0.0
        assert window.days_with_trades == 0


class TestMarkdownFormat:
    def test_markdown_output_contains_table(self) -> None:
        """format_markdown returns a string with the per-analyst table header."""
        from analytics.risk_attribution import attribute_window, format_markdown

        db = _make_db([])
        window = attribute_window(date(2026, 5, 1), date(2026, 5, 7), db_path=db)
        md = format_markdown(window)

        assert "# Risk Attribution:" in md
        assert "| Analyst |" in md
        assert "technical" in md
        assert "corey" in md


class TestRouteMarkdownResponse:
    def test_route_returns_markdown_when_requested(self) -> None:
        """
        The /attribution/window?format=markdown route returns text/markdown content.
        Uses TestClient with a minimal FastAPI app that mounts only the attribution router.
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from routers.attribution_router import router

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/attribution/window?days=7&format=markdown")

        # Should succeed (engine DB may be empty but endpoint doesn't error)
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers.get("content-type", "")
        assert "# Risk Attribution:" in resp.text
