"""Tests for the calendar Phase-4 combination layer."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import calendar_combos as cc


def _stream(vals, start="2010-01-01"):
    idx = pd.bdate_range(start, periods=len(vals))
    return pd.Series(np.asarray(vals, dtype=float), index=idx)


def test_align_restricts_to_shared_window_and_zero_fills():
    a = _stream([0.01] * 100, "2010-01-01")
    b = _stream([0.01] * 100, "2010-02-01")  # starts later
    df = cc.align([a, b])
    assert df.index[0] == max(a.index[0], b.index[0])
    assert df.index[-1] == min(a.index[-1], b.index[-1])
    assert not df.isna().any().any()


def test_correlation_ignores_both_flat_days():
    idx = pd.bdate_range("2010-01-01", periods=8)
    a = pd.Series([0, 0, 0.02, -0.02, 0, 0, 0.03, -0.03], index=idx, name="a")
    b = pd.Series([0, 0, 0.02, -0.02, 0, 0, 0.03, -0.03], index=idx, name="b")
    m = cc.correlation_matrix(pd.concat([a, b], axis=1))
    # identical on the live days -> ~1.0, not diluted by the 4 both-flat days
    assert m.loc["a", "b"] > 0.99


def test_disjoint_day_sleeves_are_uncorrelated():
    """Two sleeves that are NEVER live on the same day must read ~0 correlation
    (the disjoint-seasonal case the book exists to exploit)."""
    idx = pd.bdate_range("2010-01-01", periods=8)
    a = pd.Series([0.02, -0.02, 0, 0, 0.02, -0.02, 0, 0], index=idx, name="a")
    b = pd.Series([0, 0, 0.03, -0.03, 0, 0, 0.03, -0.03], index=idx, name="b")
    m = cc.correlation_matrix(pd.concat([a, b], axis=1))
    assert abs(m.loc["a", "b"]) < cc.CORR_THRESHOLD


def test_active_metrics_uses_only_held_days():
    # 4 held days with positive drift, padded with flat days; Sharpe must reflect
    # the held distribution, not be diluted to ~0 by the flat days.
    idx = pd.bdate_range("2010-01-01", periods=10)
    s = pd.Series([0.01, 0.012, 0.009, 0.011, 0, 0, 0, 0, 0, 0], index=idx)
    sharpe, dd = cc._active_metrics(s)
    assert sharpe > 0
    assert 0.0 <= dd <= 100.0


def test_effect_fns_cover_the_screened_family():
    # the combo layer must be able to reconstruct every screened effect's mask
    from backtest.daily_calendar_discovery import EFFECTS

    assert set(cc.EFFECT_FNS) == {name for name, _ in EFFECTS}
    assert "pre_holiday" in cc.EFFECT_FNS and "santa_claus" in cc.EFFECT_FNS
