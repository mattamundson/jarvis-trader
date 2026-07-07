"""PortfolioAllocator — core sizing/Kelly/covariance coverage (offline, no DB/network).

The existing ``test_portfolio_allocator_malformed_params`` only exercises the two
JSON-parse guards. This file covers the actual capital-allocation logic, which
sizes risk across every (strategy, symbol) cell and was previously untested:

- ``calculate_allocations``: insufficient-history default, half-Kelly sizing,
  the per-cell 2.5% cap, the per-family 5% scaling, and the loss-clamp to 0.
- ``_adjust_for_covariance``: empty/short-circuit paths + correlation down-scaling.
- ``get_risk_pct``: lookup + 1% default fallback.

A bug in any of these mis-sizes live capital, so the invariants (never exceed the
per-cell cap, never go negative, degrade to a safe 1% default) are the point.
The DB is a MagicMock — ``calculate_allocations`` only reads trades via
``db.fetch_all``; the allocation math itself is pure.
"""

from __future__ import annotations

import json
import logging

import pytest

from execution.portfolio_allocator import PortfolioAllocator

try:  # MagicMock import kept tolerant across stdlib layouts
    from unittest.mock import MagicMock
except ImportError:  # pragma: no cover
    from mock import MagicMock  # type: ignore

_LOGGER = "jarvis_trader.execution.allocator"
PER_CELL_CAP = 0.025


def _allocator(trades=None) -> PortfolioAllocator:
    db = MagicMock()
    db.fetch_all.return_value = trades if trades is not None else []
    return PortfolioAllocator(db_manager=db)


def _trade(strategy: str, symbol: str, pnl: float, exit_time: str = "2026-06-01T15:00:00"):
    return {
        "id": abs(hash((strategy, symbol, pnl))) % 100000,
        "strategy_params": json.dumps({"strategy_name": strategy}),
        "symbol": symbol,
        "pnl": pnl,
        "exit_time": exit_time,
        "status": "closed",
    }


# ── get_risk_pct ──────────────────────────────────────────────────────────


def test_get_risk_pct_defaults_to_one_percent_when_unknown():
    alloc = _allocator()
    assert alloc.get_risk_pct("no_such_strategy", "MES") == 0.01


def test_get_risk_pct_returns_active_weight_when_present():
    alloc = _allocator()
    alloc.active_weights = {("sma_trend", "MES"): 0.018}
    assert alloc.get_risk_pct("sma_trend", "MES") == 0.018
    # a different symbol still falls back to the 1% default
    assert alloc.get_risk_pct("sma_trend", "MGC") == 0.01


# ── calculate_allocations: insufficient history ───────────────────────────


@pytest.mark.asyncio
async def test_calculate_allocations_empty_history_returns_default():
    alloc = _allocator(trades=[])
    out = await alloc.calculate_allocations()
    assert out == {"status": "default", "default_risk_pct": 0.01}


@pytest.mark.asyncio
async def test_calculate_allocations_under_ten_trades_returns_default():
    # 9 trades (< 10) -> not enough history, safe 1% default.
    trades = [_trade("sma_trend", "MES", 10.0) for _ in range(9)]
    out = await _allocator(trades).calculate_allocations()
    assert out["status"] == "default"
    assert out["default_risk_pct"] == 0.01


# ── calculate_allocations: Kelly sizing + caps ────────────────────────────


@pytest.mark.asyncio
async def test_calculate_allocations_strong_cell_never_exceeds_per_cell_cap():
    # 12 trades, strongly +EV single cell -> raw half-Kelly is large (~0.31),
    # but the final weight must never exceed the 2.5% per-cell cap (and the
    # per-family scaling can only push it further DOWN, never up).
    trades = [_trade("sma_trend", "MES", 100.0) for _ in range(9)]
    trades += [_trade("sma_trend", "MES", -50.0) for _ in range(3)]
    out = await _allocator(trades).calculate_allocations()

    assert out["status"] == "success"
    weights = out["allocations"]
    assert "sma_trend:MES" in weights
    v = weights["sma_trend:MES"]
    assert 0.0 < v <= PER_CELL_CAP + 1e-9  # cap is a hard ceiling


@pytest.mark.asyncio
async def test_calculate_allocations_all_weights_respect_cap_invariant():
    # Two cells across two families; assert the global invariant holds for all.
    trades = [_trade("sma_trend", "MES", 80.0) for _ in range(6)]
    trades += [_trade("sma_trend", "MES", -40.0) for _ in range(2)]
    trades += [_trade("rsi_revert", "MGC", 60.0) for _ in range(5)]
    trades += [_trade("rsi_revert", "MGC", -30.0) for _ in range(2)]
    out = await _allocator(trades).calculate_allocations()
    assert out["status"] == "success"
    for cell, v in out["allocations"].items():
        assert 0.0 <= v <= PER_CELL_CAP + 1e-9, f"{cell} breached cap: {v}"


@pytest.mark.asyncio
async def test_calculate_allocations_losing_cell_clamps_to_zero():
    # Heavily -EV cell -> half-Kelly is negative -> clamped to max(0, ...) = 0.
    trades = [_trade("bad_trend", "MES", 50.0) for _ in range(3)]
    trades += [_trade("bad_trend", "MES", -100.0) for _ in range(9)]
    out = await _allocator(trades).calculate_allocations()
    assert out["status"] == "success"
    assert out["allocations"]["bad_trend:MES"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_calculate_allocations_sparse_cell_uses_one_percent_before_caps(caplog):
    # Total >= 10 trades, but one cell has < 5 -> that cell defaults to 0.01 raw.
    # 8 trades in cell A (>=5), 3 in cell B (<5) = 11 total.
    trades = [_trade("a_trend", "MES", 70.0, f"2026-06-0{(i % 5) + 1}T15:00:00") for i in range(8)]
    trades += [_trade("b_rev", "MGC", 5.0, f"2026-06-0{i + 1}T15:00:00") for i in range(3)]
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        out = await _allocator(trades).calculate_allocations()
    assert out["status"] == "success"
    # The sparse cell is still present and within the cap (0.01 raw, possibly scaled).
    assert "b_rev:MGC" in out["allocations"]
    assert 0.0 <= out["allocations"]["b_rev:MGC"] <= PER_CELL_CAP + 1e-9


# ── _adjust_for_covariance ────────────────────────────────────────────────


def test_covariance_empty_raw_returns_empty():
    assert _allocator()._adjust_for_covariance({}, []) == {}


def test_covariance_single_cell_short_circuits_unchanged():
    # < 2 cells in the pivot -> correlation is undefined -> raw returned as-is.
    raw = {("solo", "MES"): 0.02}
    trades = [_trade("solo", "MES", 10.0)]
    out = _allocator()._adjust_for_covariance(raw, trades)
    assert out == raw


def test_covariance_correlated_cells_are_scaled_down():
    # Two cells with identical daily P&L across 3 days -> correlation 1.0 ->
    # avg_corr (incl. self) = 1.0 -> scaling 1/(1+1) = 0.5 on each weight.
    raw = {("A", "MES"): 0.02, ("B", "MGC"): 0.02}
    trades = []
    for d, p in zip(("2026-06-01", "2026-06-02", "2026-06-03"), (10.0, 20.0, 30.0), strict=True):
        trades.append(_trade("A", "MES", p, f"{d}T15:00:00"))
        trades.append(_trade("B", "MGC", p, f"{d}T15:00:00"))
    out = _allocator()._adjust_for_covariance(raw, trades)
    # Both weights reduced from their raw 0.02 because the cells are correlated.
    assert out[("A", "MES")] < 0.02
    assert out[("B", "MGC")] < 0.02
    assert out[("A", "MES")] == pytest.approx(0.01)


def test_covariance_cell_absent_from_matrix_passes_through_unchanged():
    # A raw key whose cell_id never appears in the trades is returned untouched.
    raw = {("A", "MES"): 0.02, ("B", "MGC"): 0.02, ("ghost", "ZZ"): 0.02}
    trades = []
    for d, p in zip(("2026-06-01", "2026-06-02", "2026-06-03"), (10.0, -5.0, 15.0), strict=True):
        trades.append(_trade("A", "MES", p, f"{d}T15:00:00"))
        trades.append(_trade("B", "MGC", -p, f"{d}T15:00:00"))
    out = _allocator()._adjust_for_covariance(raw, trades)
    assert out[("ghost", "ZZ")] == 0.02  # untouched passthrough
