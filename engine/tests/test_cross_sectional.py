"""R3/T11: cross-sectional momentum signal engine (pure, no look-ahead)."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("API_KEY", "test-key")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from analysis import cross_sectional as xs  # noqa: E402
from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402


def _panel(data: dict, n: int) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(data, index=idx)


# ── panel assembly (T12) ────────────────────────────────────────────────────────────


def _ohlcv(closes: list[float], dates: list[str]) -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    return pd.DataFrame({"close": closes}, index=idx)


def test_assemble_inner_joins_common_dates():
    frames = {
        "A": _ohlcv([1.0, 2.0, 3.0], ["2026-01-01", "2026-01-02", "2026-01-03"]),
        "B": _ohlcv([10.0, 20.0], ["2026-01-02", "2026-01-03"]),  # missing 01-01
    }
    panel = xs.assemble_close_panel(frames)
    assert list(panel.columns) == ["A", "B"]
    # 01-01 dropped (B absent); only common dates remain, in order.
    assert [str(d.date()) for d in panel.index] == ["2026-01-02", "2026-01-03"]
    assert panel["A"].tolist() == [2.0, 3.0]


def test_assemble_no_ffill_on_interior_gap():
    frames = {
        "A": _ohlcv([1.0, 2.0, 3.0], ["2026-01-01", "2026-01-02", "2026-01-03"]),
        "B": _ohlcv([10.0, 30.0], ["2026-01-01", "2026-01-03"]),  # interior 01-02 gap
    }
    panel = xs.assemble_close_panel(frames)
    # 01-02 dropped, NOT forward-filled from B's 01-01 value.
    assert [str(d.date()) for d in panel.index] == ["2026-01-01", "2026-01-03"]
    assert 20.0 not in panel["B"].tolist()


def test_assemble_skips_empty_or_missing_close():
    frames = {
        "A": _ohlcv([1.0, 2.0], ["2026-01-01", "2026-01-02"]),
        "B": None,
        "C": pd.DataFrame(),
    }
    panel = xs.assemble_close_panel(frames)
    assert list(panel.columns) == ["A"]


def test_load_basket_panel_uses_injected_loader():
    store = {
        "A": _ohlcv([1.0, 2.0, 3.0], ["2026-01-01", "2026-01-02", "2026-01-03"]),
        "B": _ohlcv([10.0, 20.0, 30.0], ["2026-01-01", "2026-01-02", "2026-01-03"]),
    }

    class _Loader:
        def load(self, symbol, start, end, interval="1d"):
            return store.get(symbol)

    panel = xs.load_basket_panel(["A", "B"], "2026-01-01", "2026-01-03", loader=_Loader())
    assert list(panel.columns) == ["A", "B"]
    assert len(panel) == 3


# ── momentum ──────────────────────────────────────────────────────────────────────


def test_momentum_is_trailing_return():
    p = _panel({"A": [100.0, 110.0, 121.0], "B": [100.0, 100.0, 100.0]}, 3)
    mom = xs.compute_xs_momentum(p, lookback=1)
    # row 0 NaN (warmup); row1 A=+10%, B=0; row2 A=+10%, B=0
    assert pd.isna(mom["A"].iloc[0])
    assert mom["A"].iloc[1] == pytest.approx(0.10)
    assert mom["B"].iloc[1] == pytest.approx(0.0)
    assert mom["A"].iloc[2] == pytest.approx(0.10)


def test_momentum_lookback_window_length():
    p = _panel({"A": [100.0, 110.0, 132.0]}, 3)
    mom = xs.compute_xs_momentum(p, lookback=2)
    assert pd.isna(mom["A"].iloc[1])  # only 1 row of history at index1
    assert mom["A"].iloc[2] == pytest.approx(0.32)  # 132/100 - 1


def test_momentum_no_lookahead():
    # Changing a FUTURE price must not change a past momentum value.
    p1 = _panel({"A": [100.0, 110.0, 120.0, 130.0]}, 4)
    p2 = p1.copy()
    p2.loc[p2.index[3], "A"] = 999.0  # perturb only the last bar
    m1 = xs.compute_xs_momentum(p1, lookback=1)
    m2 = xs.compute_xs_momentum(p2, lookback=1)
    # momentum at rows 0..2 identical; only row 3 differs.
    assert m1["A"].iloc[1] == m2["A"].iloc[1]
    assert m1["A"].iloc[2] == m2["A"].iloc[2]
    assert m1["A"].iloc[3] != m2["A"].iloc[3]


def test_momentum_rejects_bad_lookback():
    with pytest.raises(ValueError):
        xs.compute_xs_momentum(_panel({"A": [1.0, 2.0]}, 2), lookback=0)


# ── dispersion ──────────────────────────────────────────────────────────────────────


def test_dispersion_higher_when_returns_spread():
    tight = _panel({"A": [100.0, 101.0], "B": [100.0, 101.0]}, 2)  # identical returns
    spread = _panel({"A": [100.0, 120.0], "B": [100.0, 90.0]}, 2)  # +20% vs -10%
    d_tight = xs.compute_dispersion(tight).iloc[1]
    d_spread = xs.compute_dispersion(spread).iloc[1]
    assert d_tight == pytest.approx(0.0)
    assert d_spread > d_tight


# ── ranking ───────────────────────────────────────────────────────────────────────


def test_rank_orders_symbols():
    scores = _panel({"A": [0.1, 0.3], "B": [0.2, 0.1], "C": [0.05, 0.2]}, 2)
    ranks = xs.rank_cross_section(scores)
    # row0: C(0.05)=1, A(0.10)=2, B(0.20)=3
    assert ranks["C"].iloc[0] == 1
    assert ranks["A"].iloc[0] == 2
    assert ranks["B"].iloc[0] == 3
    # row1: B(0.1)=1, C(0.2)=2, A(0.3)=3
    assert ranks["B"].iloc[1] == 1
    assert ranks["A"].iloc[1] == 3


def test_rank_all_nan_row_stays_nan():
    scores = _panel({"A": [float("nan"), 0.3], "B": [float("nan"), 0.1]}, 2)
    ranks = xs.rank_cross_section(scores)
    assert ranks.iloc[0].isna().all()
    assert not ranks.iloc[1].isna().any()


# ── dollar-neutral weights ──────────────────────────────────────────────────────────


def test_weights_net_to_zero_and_gross_to_one():
    scores = _panel({"A": [0.3], "B": [0.1], "C": [0.2], "D": [-0.1]}, 1)
    w = xs.dollar_neutral_weights(scores, top_k=1)
    row = w.iloc[0]
    assert row.sum() == pytest.approx(0.0)  # dollar-neutral
    assert row.abs().sum() == pytest.approx(1.0)  # gross 100%


def test_weights_long_top_short_bottom():
    scores = _panel({"A": [0.3], "B": [0.1], "C": [0.2], "D": [-0.5]}, 1)
    w = xs.dollar_neutral_weights(scores, top_k=1).iloc[0]
    assert w["A"] > 0  # highest momentum -> long
    assert w["D"] < 0  # lowest momentum -> short
    assert w["B"] == 0 and w["C"] == 0  # middle -> flat


def test_weights_top_k_two():
    scores = _panel({"A": [0.4], "B": [0.3], "C": [0.2], "D": [0.1]}, 1)
    w = xs.dollar_neutral_weights(scores, top_k=2).iloc[0]
    assert w["A"] > 0 and w["B"] > 0  # top 2 long
    assert w["C"] < 0 and w["D"] < 0  # bottom 2 short
    assert w.sum() == pytest.approx(0.0)
    assert w.abs().sum() == pytest.approx(1.0)


def test_weights_flat_when_insufficient_symbols():
    # top_k=1 needs >=2 scored symbols; one valid -> flat row.
    scores = _panel({"A": [0.3], "B": [float("nan")]}, 1)
    w = xs.dollar_neutral_weights(scores, top_k=1).iloc[0]
    assert (w == 0).all()


# ── contracts (CONTRACT_SPECS) ──────────────────────────────────────────────────────


def test_contract_positions_higher_multiplier_fewer_contracts():
    # MES multiplier 5.0, MNQ multiplier 2.0; same +0.5 dollar weight, same price.
    w = _panel({"MES": [0.5], "MNQ": [0.5]}, 1)
    prices = _panel({"MES": [100.0], "MNQ": [100.0]}, 1)
    pos = xs.compute_contract_positions(w, prices, CONTRACT_SPECS, capital=100_000.0)
    # MES: 50000 / (100*5) = 100 ; MNQ: 50000 / (100*2) = 250
    assert pos["MES"].iloc[0] == pytest.approx(100.0)
    assert pos["MNQ"].iloc[0] == pytest.approx(250.0)
    assert pos["MES"].iloc[0] < pos["MNQ"].iloc[0]


def test_contract_positions_sign_follows_weight():
    w = _panel({"MES": [0.5], "M2K": [-0.5]}, 1)
    prices = _panel({"MES": [100.0], "M2K": [100.0]}, 1)
    pos = xs.compute_contract_positions(w, prices, CONTRACT_SPECS, capital=100_000.0)
    assert pos["MES"].iloc[0] > 0
    assert pos["M2K"].iloc[0] < 0


def test_contract_positions_missing_spec_raises():
    w = _panel({"BOGUS": [0.5]}, 1)
    prices = _panel({"BOGUS": [100.0]}, 1)
    with pytest.raises(KeyError):
        xs.compute_contract_positions(w, prices, CONTRACT_SPECS, capital=100_000.0)
