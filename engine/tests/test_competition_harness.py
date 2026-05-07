"""
Unit tests for CompetitionHarness (Strategy Novel #4).

Covers:
  * Equal-weight initialisation
  * Profit-factor and Sharpe scoring math
  * Softmax weight reallocation concentrates on winner
  * `revive_losers` resets capital but preserves weight
  * `min_trades_for_scoring` zeroes under-traded competitors
  * Argmax fallback when temperature=0
  * to_dict() serialisation contract
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from strategy_lab.competition_harness import (
    CompetitionHarness,
    Competitor,
    TradeOutcome,
    _softmax,
    compute_profit_factor,
    compute_sharpe,
)

# ── Pure helpers ─────────────────────────────────────────────────────────────

def test_profit_factor_winners_only_returns_inf():
    trades = [TradeOutcome(datetime.now(), 100.0), TradeOutcome(datetime.now(), 50.0)]
    assert compute_profit_factor(trades) == float("inf")


def test_profit_factor_losers_only_returns_zero():
    trades = [TradeOutcome(datetime.now(), -100.0), TradeOutcome(datetime.now(), -50.0)]
    assert compute_profit_factor(trades) == 0.0


def test_profit_factor_mixed():
    trades = [
        TradeOutcome(datetime.now(), 200.0),   # gross_win=200
        TradeOutcome(datetime.now(), -100.0),  # gross_loss=100
    ]
    assert compute_profit_factor(trades) == 2.0


def test_profit_factor_empty():
    assert compute_profit_factor([]) == 0.0


def test_sharpe_zero_variance_returns_zero():
    trades = [TradeOutcome(datetime.now(), 100.0)] * 5
    assert compute_sharpe(trades) == 0.0


def test_sharpe_single_trade_returns_zero():
    trades = [TradeOutcome(datetime.now(), 100.0)]
    assert compute_sharpe(trades) == 0.0


def test_sharpe_positive_for_consistent_winner():
    trades = [
        TradeOutcome(datetime.now(), 100.0),
        TradeOutcome(datetime.now(), 110.0),
        TradeOutcome(datetime.now(), 90.0),
        TradeOutcome(datetime.now(), 105.0),
    ]
    s = compute_sharpe(trades)
    assert s > 0


def test_softmax_sums_to_one():
    out = _softmax([1.0, 2.0, 3.0])
    assert abs(sum(out) - 1.0) < 1e-9


def test_softmax_zero_temperature_is_argmax():
    out = _softmax([1.0, 5.0, 2.0], temperature=0)
    assert out == [0.0, 1.0, 0.0]


def test_softmax_empty_returns_empty():
    assert _softmax([]) == []


# ── Harness construction ─────────────────────────────────────────────────────

def test_construction_equal_weights():
    h = CompetitionHarness(["A", "B", "C", "D"], starting_capital=1000.0)
    weights = h.weights
    assert len(weights) == 4
    assert all(abs(w - 0.25) < 1e-9 for w in weights.values())


def test_construction_rejects_empty_strategy_list():
    with pytest.raises(ValueError, match="non-empty"):
        CompetitionHarness([])


def test_construction_rejects_nonpositive_capital():
    with pytest.raises(ValueError, match="capital"):
        CompetitionHarness(["A", "B"], starting_capital=0)


# ── Trade ingestion ──────────────────────────────────────────────────────────

def test_record_trade_updates_capital():
    h = CompetitionHarness(["A", "B"], starting_capital=1000.0)
    h.record_trade("A", TradeOutcome(datetime.now(), 50.0))
    assert h.competitors["A"].capital == 1050.0
    assert h.competitors["B"].capital == 1000.0


def test_record_trade_unknown_strategy_raises():
    h = CompetitionHarness(["A", "B"])
    with pytest.raises(KeyError):
        h.record_trade("Z", TradeOutcome(datetime.now(), 10.0))


# ── Scoring + reallocation ──────────────────────────────────────────────────

def test_score_window_concentrates_weight_on_winner():
    """Three strategies, only the winner has profitable trades. Weight should
    concentrate on the winner."""
    now = datetime(2026, 4, 16, 12, 0)
    h = CompetitionHarness(
        ["winner", "flat", "loser"],
        starting_capital=1000.0,
        window_days=30,
        scoring_metric="pf_sqrt_n",
        min_trades_for_scoring=5,
    )

    # Winner: 8 trades, mostly winning
    for i in range(8):
        h.record_trade("winner", TradeOutcome(now - timedelta(days=i), 50.0 if i % 4 != 0 else -10.0))

    # Flat: 6 break-even trades
    for i in range(6):
        h.record_trade("flat", TradeOutcome(now - timedelta(days=i), 5.0 if i % 2 == 0 else -5.0))

    # Loser: 7 trades, mostly losing
    for i in range(7):
        h.record_trade("loser", TradeOutcome(now - timedelta(days=i), -30.0 if i % 4 != 0 else 5.0))

    weights = h.score_window(window_end=now + timedelta(days=1))

    assert h.best_competitor() == "winner"
    assert weights["winner"] > weights["flat"]
    assert weights["winner"] > weights["loser"]
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_score_window_skips_under_traded_competitors():
    """A competitor with fewer than min_trades_for_scoring gets score 0."""
    now = datetime(2026, 4, 16, 12, 0)
    h = CompetitionHarness(
        ["active", "lazy"],
        window_days=30,
        scoring_metric="pf_sqrt_n",
        min_trades_for_scoring=5,
    )
    for i in range(8):
        h.record_trade("active", TradeOutcome(now - timedelta(days=i), 25.0))
    h.record_trade("lazy", TradeOutcome(now, 1000.0))  # only 1 trade

    weights = h.score_window(window_end=now + timedelta(days=1))
    # Both score nonzero (active wins infinity-PF; lazy gets 0). After softmax
    # the weight should overwhelmingly favor active.
    assert weights["active"] > weights["lazy"]


def test_revive_losers_resets_capital_but_preserves_weight():
    now = datetime(2026, 4, 16, 12, 0)
    h = CompetitionHarness(
        ["winner", "loser"],
        starting_capital=1000.0,
        window_days=30,
        revive_losers=True,
        min_trades_for_scoring=3,
    )
    for i in range(5):
        h.record_trade("winner", TradeOutcome(now - timedelta(days=i), 100.0))
    for i in range(5):
        h.record_trade("loser", TradeOutcome(now - timedelta(days=i), -100.0))

    h.score_window(window_end=now + timedelta(days=1))

    # Capital reset
    assert h.competitors["winner"].capital == 1000.0
    assert h.competitors["loser"].capital == 1000.0
    # But weight reflects performance
    assert h.competitors["winner"].weight > h.competitors["loser"].weight


def test_window_history_records_snapshot():
    now = datetime(2026, 4, 16, 12, 0)
    h = CompetitionHarness(["A", "B"], window_days=30, min_trades_for_scoring=2)
    for i in range(3):
        h.record_trade("A", TradeOutcome(now - timedelta(days=i), 30.0))
        h.record_trade("B", TradeOutcome(now - timedelta(days=i), -30.0))

    h.score_window(window_end=now + timedelta(days=1))
    h.score_window(window_end=now + timedelta(days=2))

    assert len(h.window_history) == 2
    snap = h.window_history[0]
    assert snap["scoring_metric"] == "pf_sqrt_n"
    assert "weights" in snap and "scores" in snap and "n_trades" in snap


# ── Serialisation ───────────────────────────────────────────────────────────

def test_to_dict_shape():
    h = CompetitionHarness(["A", "B"], starting_capital=500.0, window_days=14)
    d = h.to_dict()
    assert d["window_days"] == 14
    assert "competitors" in d
    assert set(d["competitors"]) == {"A", "B"}
    assert all("weight" in v and "capital" in v for v in d["competitors"].values())
