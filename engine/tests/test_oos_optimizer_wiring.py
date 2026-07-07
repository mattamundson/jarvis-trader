"""The strategy optimizer records an advisory OOS-access on each campaign.

Wires the #234 OOS-access ledger into StrategyOptimizer.run_loop (pitfall #4).
Advisory: it records + warns but must never block or raise into the loop. These
tests monkeypatch the ledger so the real engine/data ledger is never touched, and
use max_iterations=0 so no backtest runs.
"""

import logging

import pytest

from analytics.oos_access_ledger import BudgetStatus
from optimization import strategy_optimizer as so


def _fake_status(exceeded: bool) -> BudgetStatus:
    return BudgetStatus(
        dataset="2025_oos", quarter="2026Q3",
        used=3 if exceeded else 1, cap=3,
        remaining=0 if exceeded else 2, exceeded=exceeded,
    )


def test_run_loop_records_one_oos_access(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "analytics.oos_access_ledger.record_access",
        lambda purpose, **kw: calls.append((purpose, kw)) or {"purpose": purpose},
    )
    monkeypatch.setattr(
        "analytics.oos_access_ledger.budget_status", lambda **kw: _fake_status(False)
    )
    opt = so.StrategyOptimizer(symbol="MES", interval="1h", dry_run=True)
    opt.run_loop(max_iterations=0)  # no iterations -> no backtest

    assert len(calls) == 1
    purpose, kw = calls[0]
    assert "MES" in purpose
    assert kw["extra"]["symbol"] == "MES"


def test_run_loop_warns_when_budget_exceeded(monkeypatch, caplog):
    monkeypatch.setattr(
        "analytics.oos_access_ledger.record_access", lambda purpose, **kw: {"purpose": purpose}
    )
    monkeypatch.setattr(
        "analytics.oos_access_ledger.budget_status", lambda **kw: _fake_status(True)
    )
    opt = so.StrategyOptimizer(symbol="MGC", interval="1h", dry_run=True)
    with caplog.at_level(logging.WARNING):
        opt.run_loop(max_iterations=0)
    assert any("OOS-access budget spent" in r.message for r in caplog.records)


def test_ledger_failure_never_breaks_the_loop(monkeypatch):
    """A ledger error must be swallowed — accounting never blocks optimization."""
    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("analytics.oos_access_ledger.record_access", _boom)
    opt = so.StrategyOptimizer(symbol="MES", interval="1h", dry_run=True)
    # Should complete and return best_params despite the ledger raising.
    result = opt.run_loop(max_iterations=0)
    assert isinstance(result, dict)
