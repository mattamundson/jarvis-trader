"""
Regression tests for GT-05 — drawdown_pct structurally always reported -0.0 on
the /health circuit-breaker section and on /mission-control (not just a
today's-value coincidence).

Root cause: ``PortfolioTracker.get_performance()`` (portfolio/tracker.py) never
included an ``equity_curve`` key in its return dict. ``PnLMonitor.get_drawdown_pct()``
(risk/pnl_monitor.py) reads ``perf.get("equity_curve", [])`` to find the
all-time equity peak on the ``source="memory"`` path; with the key always
absent, ``curve`` was always ``[]``, ``peak = max([], default=0.0) == 0.0``,
and the ``peak > 0`` guard was always False — so the method always returned
positive ``0.0`` regardless of the account's true drawdown depth.
``SafetyLayer.check_circuit_breakers()`` (risk/safety_layer.py:2149) then
negates that value (``drawdown_pct = -pnl_monitor.get_drawdown_pct()``), which
turns the IEEE-754 positive ``0.0`` into ``-0.0`` — the exact symptom reported
on /health's ``circuit_breakers`` section and on /mission-control's
RiskSafetyPanel, masking any real drawdown straight through a breach.

Fix (engine/portfolio/tracker.py): ``get_performance()`` now returns an
``equity_curve`` key — the absolute account equity (starting_balance +
cumulative closed pnl) after each closed trade — which is the series
downstream consumers actually need (they compare it against an absolute
``current_balance`` computed the same way).

Fixture: account peaks at $15,147.98 then drops to $14,950.00 — a real
~1.31% drawdown. These tests assert the computed drawdown_pct is close to
that true value, not 0.0 or -0.0.

Note: risk/safety_layer.py is Edit/Write-denied for this fix (GT-05 is scoped
to the upstream data-population bug in portfolio/tracker.py), so the negation
SafetyLayer performs is reproduced inline here (mirroring its own line 2149)
rather than imported, to keep this regression coverage independent of that
file.
"""

from __future__ import annotations

import pytest

from config import settings as _settings
from portfolio.tracker import PortfolioTracker
from risk.pnl_monitor import PnLMonitor

PEAK_EQUITY = 15_147.98
CURRENT_EQUITY = 14_950.00
TRUE_DRAWDOWN_PCT = (CURRENT_EQUITY - PEAK_EQUITY) / PEAK_EQUITY  # ≈ -0.013069


class _StubDB:
    """Minimal stand-in for DatabaseManager.get_closed_trades()."""

    def __init__(self, rows):
        self._rows = rows

    def get_closed_trades(self, limit: int = 10000):
        return self._rows


def _make_tracker(tmp_path, monkeypatch, starting_balance: float = 10_000.0) -> PortfolioTracker:
    """PortfolioTracker with two closed trades reproducing the fixture:
    account equity peaks at $15,147.98 then closes at $14,950.00.
    """
    monkeypatch.setattr(_settings, "INITIAL_CAPITAL", starting_balance)

    win_pnl = PEAK_EQUITY - starting_balance  # +5,147.98 -> equity peaks here
    loss_pnl = CURRENT_EQUITY - PEAK_EQUITY  # -197.98 -> equity ends here

    db = _StubDB(
        [
            {"trade_id": "t1", "pnl": win_pnl, "exit_time": "2026-07-20T15:00:00"},
            {"trade_id": "t2", "pnl": loss_pnl, "exit_time": "2026-07-21T15:00:00"},
        ]
    )
    return PortfolioTracker(store_path=tmp_path / "trades.jsonl", db_manager=db)


# ── PortfolioTracker.get_performance() — equity_curve population ────────────


class TestGetPerformanceEquityCurve:
    def test_equity_curve_key_present(self, tmp_path, monkeypatch):
        tracker = _make_tracker(tmp_path, monkeypatch)
        perf = tracker.get_performance()
        assert "equity_curve" in perf, (
            "get_performance() must return an 'equity_curve' key -- GT-05 regression: "
            "downstream drawdown consumers silently floor at 0.0/-0.0 without it."
        )

    def test_equity_curve_values_are_absolute_equity(self, tmp_path, monkeypatch):
        tracker = _make_tracker(tmp_path, monkeypatch, starting_balance=10_000.0)
        perf = tracker.get_performance()
        curve = perf["equity_curve"]

        assert curve[0] == pytest.approx(10_000.0)
        assert max(curve) == pytest.approx(PEAK_EQUITY)
        assert curve[-1] == pytest.approx(CURRENT_EQUITY)

    def test_empty_history_equity_curve_is_starting_balance_only(self, tmp_path, monkeypatch):
        """No closed trades yet -- equity_curve must still exist (peak == starting_balance)."""
        monkeypatch.setattr(_settings, "INITIAL_CAPITAL", 10_000.0)
        tracker = PortfolioTracker(store_path=tmp_path / "trades.jsonl", db_manager=_StubDB([]))
        perf = tracker.get_performance()
        assert perf["equity_curve"] == [pytest.approx(10_000.0)]


# ── PnLMonitor.get_drawdown_pct() — end-to-end with a real tracker ──────────


class TestPnLMonitorDrawdownEndToEnd:
    """source='memory' path must reflect the tracker's real equity curve --
    not silently floor at 0.0/-0.0 regardless of the true drawdown depth."""

    def test_drawdown_pct_matches_true_value(self, tmp_path, monkeypatch):
        tracker = _make_tracker(tmp_path, monkeypatch)
        monitor = PnLMonitor(db_manager=None, ib_gateway=None, paper_tracker=tracker)

        dd = monitor.get_drawdown_pct()

        assert dd != 0.0, "drawdown_pct must not floor at 0.0 -- GT-05 recurrence"
        assert dd == pytest.approx(TRUE_DRAWDOWN_PCT, rel=1e-3)
        assert dd < 0, "account is below peak -- drawdown must be negative"

    def test_negated_value_is_a_real_positive_breach_not_negative_zero(self, tmp_path, monkeypatch):
        """SafetyLayer.check_circuit_breakers() computes
        ``-pnl_monitor.get_drawdown_pct()`` (risk/safety_layer.py:2149) for the
        /health circuit_breakers section and /mission-control. Before the fix,
        get_drawdown_pct() always returned positive 0.0, and negating it
        produced IEEE-754 -0.0 -- the exact reported symptom. Reproduced here
        without importing the deny-listed risk/safety_layer.py module.
        """
        tracker = _make_tracker(tmp_path, monkeypatch)
        monitor = PnLMonitor(db_manager=None, ib_gateway=None, paper_tracker=tracker)

        drawdown_pct = -monitor.get_drawdown_pct()  # mirrors safety_layer.py:2149

        assert drawdown_pct == pytest.approx(-TRUE_DRAWDOWN_PCT, rel=1e-3)
        assert drawdown_pct > 0, (
            f"expected a real positive ~1.3% breached-from-peak reading, got {drawdown_pct}"
        )
