"""
Differential / parity test: the in-house Backtester vs NautilusTrader.

Runs one identical, deliberately-simplified strategy (SMA golden-cross entry,
death-cross exit, 1 contract, zero execution costs) through BOTH engines and
asserts they agree. This is the "second engine" the .claude/rules/testing.md
live-vs-backtest-parity discipline asks for — the custom Backtester previously
had nothing independent to check it against.

NautilusTrader (and pandas) are OPTIONAL. If either is missing the whole module
is skipped, so the suite stays green in environments without the heavy dep. See
backtest/nautilus_parity.py and docs/repo-integrations/nautechsystems__nautilus_trader.md.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pandas", reason="pandas required for parity harness")
pytest.importorskip("nautilus_trader", reason="nautilus_trader not installed (optional dep)")

from backtest.nautilus_parity import compare, make_synthetic_bars  # noqa: E402


def test_synthetic_exact_parity():
    """On gapless synthetic bars (open[i] == close[i-1]) the two engines' fill
    conventions coincide, so trade count AND net PnL must match exactly."""
    report = compare(make_synthetic_bars())
    assert report.custom.num_trades == 1, report.summary()
    assert report.nautilus.num_trades == 1, report.summary()
    assert report.trades_match, report.summary()
    # Exact on synthetic: entry (next-open) == signal-bar close, so |Δpnl| == 0.
    assert report.pnl_abs_diff == pytest.approx(0.0, abs=1e-6), report.summary()
    assert report.passed, report.summary()


def test_synthetic_is_deterministic():
    """No RNG / wall-clock: identical inputs -> identical results across runs."""
    a = compare(make_synthetic_bars())
    b = compare(make_synthetic_bars())
    assert a.custom.net_pnl == b.custom.net_pnl
    assert a.nautilus.net_pnl == b.nautilus.net_pnl
    assert a.custom.num_trades == b.custom.num_trades == 1


def test_direction_and_multiplier_are_consistent():
    """Both engines are long-only here and use the SAME instrument multiplier, so
    a single winning long trade must be positive in both. Guards against a sign
    (direction) flip or a multiplier mismatch between the engines."""
    report = compare(make_synthetic_bars())
    assert report.custom.net_pnl > 0, report.summary()
    assert report.nautilus.net_pnl > 0, report.summary()
    # Same sign — not one engine long, the other short.
    assert (report.custom.net_pnl > 0) == (report.nautilus.net_pnl > 0), report.summary()
