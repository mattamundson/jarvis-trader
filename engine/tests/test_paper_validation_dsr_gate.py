"""[safety-review] PR-10: DSR gate wired into paper_validation_router surfaces.

Covers the three live-readiness endpoints that duplicate Sharpe computation
and previously had no DSR check at all: _build_validation_gate_rows() (used
by /gates and /approved-paper-gates) and /checkpoint's own gates dict.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backtest._gate_v2_helpers import GATE_DSR, MIN_OOS_TRADES_PER_WINDOW
from routers.paper_validation_router import (
    _build_validation_gate_rows,
    _compute_dsr_ratio,
)


def _trades_from_daily_pnls(daily_pnls: list[float]) -> list[dict]:
    base = datetime(2026, 6, 1, 14, 30)
    return [
        {
            "entry_time": (base + timedelta(days=i)).isoformat() + "Z",
            "exit_time": (base + timedelta(days=i, hours=1)).isoformat() + "Z",
            "pnl": pnl,
        }
        for i, pnl in enumerate(daily_pnls)
    ]


class TestComputeDsrRatio:
    def test_matches_analytics_validation_metrics_wiring(self):
        """Same daily-bucketing shape, same DSR wrapper -- both routers'
        implementations must agree on a given trade series."""
        from analytics.validation_metrics import ValidationMetrics

        daily = [80.0, -60.0, 90.0, -50.0, 70.0, -40.0, 60.0]
        trades = _trades_from_daily_pnls(daily)

        router_result = _compute_dsr_ratio(trades)
        vm_result = ValidationMetrics()._compute_dsr(trades)

        assert router_result["dsr"] == vm_result["dsr"]
        assert router_result["n_obs"] == vm_result["n_obs"]

    def test_empty_trades_returns_zero_dsr(self):
        result = _compute_dsr_ratio([])
        assert result["dsr"] == 0.0


class TestBuildValidationGateRowsIncludesDsr:
    def test_short_lucky_streak_fails_dsr_gate(self):
        """2-day lucky streak: raw Sharpe/PF/win-rate would all look great,
        but the DSR gate must fail on insufficient observations."""
        trades = _trades_from_daily_pnls([40.0, 10.0])
        # _build_validation_gate_rows expects one dict per CLOSED TRADE, not
        # per day -- reuse the same records as individual trades (1/day here).
        gates, _avg_conviction, overall_pass = _build_validation_gate_rows(
            trades, days_for_min_days_gate=2,
        )
        by_name = {g.name: g for g in gates}
        assert "deflated_sharpe_ratio" in by_name
        assert by_name["deflated_sharpe_ratio"].passes is False
        assert overall_pass is False

    def test_solid_track_record_passes_dsr_gate(self):
        daily = [80.0 + (i % 3) * 5 for i in range(40)]
        trades = _trades_from_daily_pnls(daily)
        gates, _avg_conviction, _overall_pass = _build_validation_gate_rows(
            trades, days_for_min_days_gate=40,
        )
        by_name = {g.name: g for g in gates}
        assert by_name["deflated_sharpe_ratio"].passes is True
        assert by_name["deflated_sharpe_ratio"].target == GATE_DSR


# ── /checkpoint gates["deflated_sharpe"] ────────────────────────────────────


class MockDatabaseManager:
    def __init__(self, closed_trades: list[dict] | None = None):
        self.closed_trades = closed_trades or []

    def get_closed_trades(self, limit: int = 500) -> list[dict]:
        return self.closed_trades[:limit]


@pytest.fixture
def mock_db():
    return MockDatabaseManager()


def test_checkpoint_dsr_gate_insufficient_data_under_five_trades(mock_db, monkeypatch):
    from routers.paper_validation_router import get_validation_checkpoint

    mock_db.closed_trades = _trades_from_daily_pnls([40.0, 10.0])[:2]
    monkeypatch.setattr(
        "routers.paper_validation_router.get_db", lambda: mock_db
    )

    import asyncio

    result = asyncio.run(get_validation_checkpoint())
    assert result.gates["deflated_sharpe"].status == "INSUFFICIENT_DATA"


def test_checkpoint_dsr_gate_fails_on_thin_sample(mock_db, monkeypatch):
    from routers.paper_validation_router import get_validation_checkpoint

    # 6 trades across only 3 distinct days (clusters same-day) -- clears the
    # trade_count>=5 floor but not the DSR n_obs floor (needs
    # MIN_OOS_TRADES_PER_WINDOW=5 distinct daily buckets).
    base = datetime(2026, 6, 1, 14, 30)
    trades = []
    for day in range(3):
        for k in range(2):
            trades.append(
                {
                    "trade_id": f"t{day}_{k}",
                    "entry_time": (base + timedelta(days=day, hours=k)).isoformat() + "Z",
                    "exit_time": (base + timedelta(days=day, hours=k + 1)).isoformat() + "Z",
                    "pnl": 50.0,
                }
            )
    mock_db.closed_trades = trades
    monkeypatch.setattr(
        "routers.paper_validation_router.get_db", lambda: mock_db
    )

    import asyncio

    result = asyncio.run(get_validation_checkpoint())
    assert result.trade_count == 6
    assert result.gates["deflated_sharpe"].status == "FAIL"


def test_checkpoint_dsr_gate_passes_on_solid_sample(mock_db, monkeypatch):
    from routers.paper_validation_router import get_validation_checkpoint

    daily = [80.0 + (i % 3) * 5 for i in range(40)]
    mock_db.closed_trades = _trades_from_daily_pnls(daily)
    monkeypatch.setattr(
        "routers.paper_validation_router.get_db", lambda: mock_db
    )

    import asyncio

    result = asyncio.run(get_validation_checkpoint())
    assert result.gates["deflated_sharpe"].status == "PASS"
