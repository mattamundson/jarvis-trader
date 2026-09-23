"""
Regression — PortfolioAllocator must not silently swallow malformed
``strategy_params``.

Two read paths (``_group_trades_by_cell`` and the ``get_strategy`` helper inside
``_adjust_for_covariance``) parse the per-trade ``strategy_params`` JSON. A bare
``except Exception`` previously bucketed any parse failure under "unknown" with
no log, corrupting the correlation matrix and the correlation-adjusted
allocations invisibly. These tests assert the failure is now LOGGED (not
silent) and that a NULL ``strategy_params`` no longer crashes the grouping.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

from execution.portfolio_allocator import PortfolioAllocator

_LOGGER = "jarvis_trader.execution.allocator"


def _allocator() -> PortfolioAllocator:
    # _group_trades_by_cell / _adjust_for_covariance are pure (no DB access).
    return PortfolioAllocator(db_manager=MagicMock())


def test_group_trades_malformed_params_logs_and_buckets_unknown(caplog):
    alloc = _allocator()
    trades = [
        {"id": 7, "strategy_params": "{not valid json", "symbol": "MES", "pnl": 12.0},
    ]
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        cells = alloc._group_trades_by_cell(trades)

    # Bucketed under the safe fallback rather than dropped...
    assert ("unknown", "MES") in cells
    assert cells[("unknown", "MES")] == [12.0]
    # ...and the malformation was logged WITH the trade id, not swallowed.
    msgs = [r.getMessage() for r in caplog.records]
    assert any("Malformed strategy_params" in m for m in msgs)
    assert any("id=7" in m for m in msgs)


def test_group_trades_null_params_does_not_crash():
    alloc = _allocator()
    trades = [
        {"id": 8, "strategy_params": None, "symbol": "MGC", "regime": "trend", "pnl": -3.0},
    ]
    # A NULL strategy_params previously crashed params.get() with AttributeError.
    cells = alloc._group_trades_by_cell(trades)
    assert ("trend", "MGC") in cells
    assert cells[("trend", "MGC")] == [-3.0]


def test_group_trades_valid_params_uses_strategy_name():
    alloc = _allocator()
    trades = [
        {
            "id": 9,
            "strategy_params": json.dumps({"strategy_name": "sma_trend"}),
            "symbol": "MES",
            "pnl": 5.0,
        },
    ]
    cells = alloc._group_trades_by_cell(trades)
    assert ("sma_trend", "MES") in cells


def test_covariance_get_strategy_malformed_logs(caplog):
    alloc = _allocator()
    # get_strategy() runs inside df.apply BEFORE the <2-cell short-circuit, so the
    # malformed row is parsed (and must be logged) regardless of the corr path.
    trades = [
        {"strategy_params": "{bad", "symbol": "MES", "pnl": 10.0, "exit_time": "2026-06-01T15:00:00"},
        {
            "strategy_params": json.dumps({"strategy_name": "sma"}),
            "symbol": "MGC",
            "pnl": 5.0,
            "exit_time": "2026-06-01T15:00:00",
        },
    ]
    raw = {("unknown", "MES"): 0.02, ("sma", "MGC"): 0.02}
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        alloc._adjust_for_covariance(raw, trades)

    assert any("Malformed strategy_params" in r.getMessage() for r in caplog.records)
<<<<<<< HEAD
=======


def test_covariance_constant_pnl_column_yields_no_nan_allocation():
    """A zero-variance (constant-P&L) cell makes pandas .corr() emit a NaN
    column. The scaling at portfolio_allocator.py uses ``max(0, avg_corr)`` so
    that a NaN average correlation degrades to 0 -> scaling 1.0 (treated as
    uncorrelated), never propagating NaN into the money-path allocation.

    This pins that safe behavior: flipping the args to ``max(avg_corr, 0)``
    would leak NaN and fail this test. The varying cell still gets scaled.
    """
    import math

    alloc = _allocator()
    trades = [
        # Varying cell -> well-defined correlation column
        {"strategy_params": json.dumps({"strategy_name": "trend"}), "symbol": "MES",
         "pnl": 10.0, "exit_time": "2026-06-01T15:00:00"},
        {"strategy_params": json.dumps({"strategy_name": "trend"}), "symbol": "MES",
         "pnl": -5.0, "exit_time": "2026-06-02T15:00:00"},
        # Constant cell -> zero variance -> NaN correlation column
        {"strategy_params": json.dumps({"strategy_name": "trend"}), "symbol": "MGC",
         "pnl": 7.0, "exit_time": "2026-06-01T15:00:00"},
        {"strategy_params": json.dumps({"strategy_name": "trend"}), "symbol": "MGC",
         "pnl": 7.0, "exit_time": "2026-06-02T15:00:00"},
    ]
    raw = {("trend", "MES"): 0.5, ("trend", "MGC"): 0.5}
    adjusted = alloc._adjust_for_covariance(raw, trades)

    # No NaN may reach any allocation.
    assert all(math.isfinite(v) for v in adjusted.values())
    # The degenerate (NaN-correlation) cell falls back to scaling 1.0.
    assert adjusted[("trend", "MGC")] == 0.5
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
