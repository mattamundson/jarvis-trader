"""Tests for the Strategy-Card gate, jsonl IO, results DB, and signal adapter."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.factory.results_db import ResultsDB
from backtest.factory.signal_adapter import (
    FULL_CONTRACT,
    build_signal_frame,
    resolve_signal_fn,
)
from backtest.factory.strategy_card import StrategyCard, load_cards, save_cards


def _good_card(**over) -> StrategyCard:
    base = dict(
        name="donchian_breakout",
        family="breakout",
        signal_ref="backtest.donchian_signals:generate_donchian_signals",
        entry="close breaks N-bar high",
        exit="ATR trail / opposite channel",
        economic_rationale="Trend persistence: a fresh N-bar breakout reflects "
        "genuine order-flow imbalance that tends to continue intraday.",
        native_instruments=["MES", "MNQ"],
        native_timeframes=["1h"],
        default_params={"lookback_entry": 20, "lookback_exit": 10},
        param_grid={"lookback_entry": [20, 40], "lookback_exit": [10, 20]},
    )
    base.update(over)
    return StrategyCard(**base)


# ---- card gate -------------------------------------------------------------


def test_valid_card_passes_gate():
    assert _good_card().is_valid()


def test_thin_rationale_is_killed():
    card = _good_card(economic_rationale="momentum")
    probs = card.problems()
    assert any("rationale" in p for p in probs)
    assert not card.is_valid()


def test_bad_family_and_ref_flagged():
    assert any("family" in p for p in _good_card(family="vibes").problems())
    assert any("signal_ref" in p for p in _good_card(signal_ref="no_colon").problems())


def test_n_param_combos():
    assert _good_card().n_param_combos() == 4  # 2 x 2


def test_jsonl_roundtrip_drops_invalid(tmp_path):
    good = _good_card()
    bad = _good_card(name="bad", economic_rationale="")  # gate should drop
    path = tmp_path / "cards.jsonl"
    save_cards([good, bad], path)
    loaded = load_cards(path, drop_invalid=True)
    assert [c.name for c in loaded] == ["donchian_breakout"]
    with pytest.raises(ValueError):
        load_cards(path, drop_invalid=False)


# ---- results DB ------------------------------------------------------------


def test_results_db_counter_and_survivors(tmp_path):
    db = ResultsDB(tmp_path / "results.sqlite")
    run = db.new_run("2026-06-26T00:00:00Z", {"pilot": True})
    c1 = db.record_candidate(run, "donchian", "MES", "1h", {"lookback_entry": 20}, "smoke")
    c2 = db.record_candidate(run, "orb", "MES", "1h", {}, "smoke")
    db.record_result(c1, "smoke", {"sharpe": 0.8, "pf": 1.3}, verdict="PASS")
    db.record_result(
        c2, "smoke", {"sharpe": 0.1, "pf": 0.9}, verdict="KILL", kill_reason="sharpe<0.5"
    )
    assert db.global_trial_count() == 2
    surv = db.survivors(run, "smoke", verdict="PASS")
    assert len(surv) == 1 and surv[0]["card_name"] == "donchian"
    assert surv[0]["metrics"]["pf"] == 1.3
    db.close()


# ---- signal adapter --------------------------------------------------------


def test_resolve_signal_fn_errors():
    with pytest.raises(ValueError):
        resolve_signal_fn("no_colon_here")


def test_adapter_backfills_contract_columns():
    """A generator emitting only the required signal cols gets the full contract."""
    rng = np.random.default_rng(3)
    n = 120
    price = 100 + np.cumsum(rng.normal(0, 0.5, n))
    bars = pd.DataFrame(
        {
            "open": price,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
        },
        index=pd.date_range("2025-01-01", periods=n, freq="h"),
    )
    out = build_signal_frame(
        "backtest.donchian_signals:generate_donchian_signals",
        bars,
        {"lookback_entry": 20, "lookback_exit": 10},
    )
    for col in FULL_CONTRACT:
        assert col in out.columns, f"adapter must guarantee '{col}'"
    assert len(out) == n
