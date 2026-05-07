import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.position_sizing import calculate_half_kelly_size, compute_rolling_edge


def test_half_kelly_positive_edge():
    result = calculate_half_kelly_size(
        capital=10000,
        win_rate=0.36,
        avg_win_loss_ratio=3.5,  # MES historical (avg win ~$430, avg loss ~$123)
        tick_value=1.25,         # MES: $5/pt × 0.25 tick = $1.25/tick (CME spec)
        atr_ticks=60.0,          # ~15 pts × 4 ticks/pt
    )
    assert result['contracts'] >= 1
    assert result['method'] == 'half_kelly'
    assert result['kelly_fraction'] > 0
    assert result['contracts'] <= 2  # hard cap


def test_half_kelly_no_edge_returns_minimum():
    result = calculate_half_kelly_size(
        capital=10000,
        win_rate=0.30,
        avg_win_loss_ratio=1.0,  # break-even: no edge
        tick_value=1.25,
        atr_ticks=60.0,
    )
    assert result['contracts'] == 1
    assert 'no_edge' in result['method']


def test_half_kelly_zero_win_loss_ratio_returns_fallback():
    result = calculate_half_kelly_size(
        capital=10000,
        win_rate=0.50,
        avg_win_loss_ratio=0.0,  # degenerate input
        tick_value=1.25,
        atr_ticks=60.0,
    )
    assert result['contracts'] == 1
    assert result['method'] == 'fixed_fallback'


def test_rolling_edge_insufficient_data():
    result = compute_rolling_edge([{'pnl': 100}] * 5)
    assert not result['sufficient_data']
    assert result['n_trades'] == 5


def test_rolling_edge_with_20_trades():
    # 8 wins at $150, 12 losses at $60 → 40% win rate, avg_win/avg_loss = 2.5
    trades = [{'pnl': 150.0}] * 8 + [{'pnl': -60.0}] * 12
    result = compute_rolling_edge(trades)
    assert result['sufficient_data']
    assert abs(result['win_rate'] - 0.40) < 0.01
    assert abs(result['avg_win_loss_ratio'] - 2.5) < 0.01


def test_rolling_edge_only_wins():
    trades = [{'pnl': 100.0}] * 20
    result = compute_rolling_edge(trades)
    assert result['sufficient_data']
    assert result['win_rate'] == 1.0
