"""
Tests for engine/analytics/regime_analysis.py — US-008.

Synthetic fixtures cover:
  - All three canonical regimes with sufficient data
  - One regime with < MIN_OBS observations
  - One regime entirely absent from labels
  - Empty / NaN inputs
  - Known sharpe sign assertion for a purely-positive RISK_ON slice
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Path setup — run from repo root or engine/ dir
# ---------------------------------------------------------------------------

_ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from analytics.regime_analysis import KNOWN_REGIMES, MIN_OBS, regime_conditional_analysis

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_series(n: int, seed: int, mean: float = 0.001, std: float = 0.01) -> pd.Series:
    """Return a reproducible daily-returns Series with a DatetimeIndex."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(rng.normal(mean, std, n), index=idx)


@pytest.fixture()
def full_fixture():
    """Fixture with 60 RISK_ON, 30 RISK_OFF, 10 NORMAL days (all >= MIN_OBS)."""
    n_on, n_off, n_normal = 60, 30, 10
    total = n_on + n_off + n_normal
    returns = _make_series(total, seed=42)
    labels_raw = (
        ["RISK_ON"] * n_on
        + ["RISK_OFF"] * n_off
        + ["NORMAL"] * n_normal
    )
    labels = pd.Series(labels_raw, index=returns.index)
    return returns, labels, n_on, n_off, n_normal


@pytest.fixture()
def positive_risk_on_fixture():
    """Fixture where RISK_ON days have consistently positive returns -> Sharpe > 0."""
    n = 40
    rng = np.random.default_rng(99)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    # Mean +0.5%, std 0.1% — positive every day with tiny variance; Sharpe >> 0
    positive_rets = pd.Series(rng.normal(0.005, 0.001, n), index=idx)
    labels = pd.Series(["RISK_ON"] * n, index=idx)
    return positive_rets, labels


@pytest.fixture()
def insufficient_fixture():
    """RISK_ON has MIN_OBS-1 obs; RISK_OFF has enough; NORMAL is absent."""
    n_on = MIN_OBS - 1  # too few
    n_off = 20
    total = n_on + n_off
    returns = _make_series(total, seed=7)
    labels_raw = ["RISK_ON"] * n_on + ["RISK_OFF"] * n_off
    labels = pd.Series(labels_raw, index=returns.index)
    return returns, labels, n_on, n_off


# ---------------------------------------------------------------------------
# Basic shape + key checks
# ---------------------------------------------------------------------------


class TestOutputShape:
    def test_all_three_regimes_present(self, full_fixture):
        returns, labels, *_ = full_fixture
        out = regime_conditional_analysis(returns, labels)
        for regime in KNOWN_REGIMES:
            assert regime in out, f"Missing regime key: {regime}"

    def test_meta_key_present(self, full_fixture):
        returns, labels, *_ = full_fixture
        out = regime_conditional_analysis(returns, labels)
        assert "_meta" in out
        assert "n_aligned" in out["_meta"]
        assert out["_meta"]["n_aligned"] == len(returns)

    def test_sufficient_regimes_have_all_metric_keys(self, full_fixture):
        returns, labels, *_ = full_fixture
        out = regime_conditional_analysis(returns, labels)
        expected_keys = {"n_days", "sharpe", "sortino", "max_dd", "win_rate",
                         "tail_ratio", "skew", "calmar"}
        for regime in ("RISK_ON", "RISK_OFF"):
            assert expected_keys.issubset(out[regime].keys()), (
                f"{regime} missing keys: {expected_keys - out[regime].keys()}"
            )

    def test_n_days_correct(self, full_fixture):
        returns, labels, n_on, n_off, n_normal = full_fixture
        out = regime_conditional_analysis(returns, labels)
        assert out["RISK_ON"]["n_days"] == n_on
        assert out["RISK_OFF"]["n_days"] == n_off
        assert out["NORMAL"]["n_days"] == n_normal


# ---------------------------------------------------------------------------
# Insufficient / absent data
# ---------------------------------------------------------------------------


class TestInsufficientData:
    def test_insufficient_regime_has_note(self, insufficient_fixture):
        returns, labels, n_on, _ = insufficient_fixture
        out = regime_conditional_analysis(returns, labels)
        assert out["RISK_ON"]["note"] == "insufficient data"
        assert out["RISK_ON"]["n_days"] == n_on

    def test_absent_regime_has_no_data_note(self, insufficient_fixture):
        returns, labels, *_ = insufficient_fixture
        out = regime_conditional_analysis(returns, labels)
        assert out["NORMAL"]["n_days"] == 0
        assert out["NORMAL"]["note"] == "no data"

    def test_sufficient_regime_still_computes(self, insufficient_fixture):
        returns, labels, _, n_off = insufficient_fixture
        out = regime_conditional_analysis(returns, labels)
        assert out["RISK_OFF"]["n_days"] == n_off
        assert "note" not in out["RISK_OFF"]


# ---------------------------------------------------------------------------
# Known sharpe sign
# ---------------------------------------------------------------------------


class TestKnownSharpeSign:
    def test_positive_returns_give_positive_sharpe(self, positive_risk_on_fixture):
        returns, labels = positive_risk_on_fixture
        out = regime_conditional_analysis(returns, labels)
        sharpe = out["RISK_ON"]["sharpe"]
        assert sharpe is not None, "Sharpe should not be None for well-behaved series"
        assert sharpe > 0, f"Expected positive Sharpe for all-positive returns; got {sharpe}"

    def test_max_dd_nonpositive(self, full_fixture):
        """max_drawdown should be <= 0 (or None) for any series."""
        returns, labels, *_ = full_fixture
        out = regime_conditional_analysis(returns, labels)
        for regime in ("RISK_ON", "RISK_OFF"):
            dd = out[regime].get("max_dd")
            if dd is not None:
                assert dd <= 0, f"{regime} max_dd={dd} should be non-positive"


# ---------------------------------------------------------------------------
# Edge cases — empty / NaN inputs
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_returns_series(self):
        out = regime_conditional_analysis(pd.Series(dtype=float), pd.Series(dtype=str))
        for regime in KNOWN_REGIMES:
            assert out[regime]["n_days"] == 0
            assert "no data" in out[regime]["note"]

    def test_none_inputs(self):
        out = regime_conditional_analysis(None, None)  # type: ignore[arg-type]
        for regime in KNOWN_REGIMES:
            assert "note" in out[regime]

    def test_all_nan_returns(self):
        idx = pd.date_range("2024-01-01", periods=10, freq="B")
        returns = pd.Series([np.nan] * 10, index=idx)
        labels = pd.Series(["RISK_ON"] * 10, index=idx)
        out = regime_conditional_analysis(returns, labels)
        # After dropna, 0 observations -> no data
        assert "note" in out["RISK_ON"]

    def test_lowercase_labels_normalised(self):
        """Labels like 'risk_on' should normalise to 'RISK_ON'."""
        n = 20
        idx = pd.date_range("2024-01-01", periods=n, freq="B")
        returns = _make_series(n, seed=1)
        labels = pd.Series(["risk_on"] * n, index=idx)
        out = regime_conditional_analysis(returns, labels)
        assert out["RISK_ON"]["n_days"] == n
        assert "note" not in out["RISK_ON"]

    def test_mixed_case_labels(self):
        n = 20
        idx = pd.date_range("2024-01-01", periods=n, freq="B")
        returns = _make_series(n, seed=2)
        labels = pd.Series(["Risk_Off"] * n, index=idx)
        out = regime_conditional_analysis(returns, labels)
        assert out["RISK_OFF"]["n_days"] == n

    def test_index_misalignment_handled(self):
        """Returns and labels on different (non-overlapping) indices -> no data."""
        idx_r = pd.date_range("2024-01-01", periods=20, freq="B")
        idx_l = pd.date_range("2025-01-01", periods=20, freq="B")
        returns = _make_series(20, seed=3)
        returns.index = idx_r
        labels = pd.Series(["RISK_ON"] * 20, index=idx_l)
        out = regime_conditional_analysis(returns, labels)
        # Non-overlapping: all regimes have no data
        for regime in KNOWN_REGIMES:
            assert "note" in out[regime]

    def test_partial_index_overlap(self):
        """Overlapping subset is used; non-overlapping rows are dropped."""
        idx = pd.date_range("2024-01-01", periods=40, freq="B")
        returns = _make_series(40, seed=4)
        returns.index = idx
        # Labels only cover first 20 of the same index
        labels = pd.Series(["RISK_ON"] * 20, index=idx[:20])
        out = regime_conditional_analysis(returns, labels)
        assert out["RISK_ON"]["n_days"] == 20


# ---------------------------------------------------------------------------
# Metric types
# ---------------------------------------------------------------------------


class TestMetricTypes:
    def test_numeric_metrics_are_float_or_none(self, full_fixture):
        returns, labels, *_ = full_fixture
        out = regime_conditional_analysis(returns, labels)
        float_keys = ("sharpe", "sortino", "max_dd", "win_rate", "tail_ratio", "skew", "calmar")
        for regime in ("RISK_ON", "RISK_OFF", "NORMAL"):
            for key in float_keys:
                val = out[regime].get(key)
                assert val is None or isinstance(val, float), (
                    f"{regime}.{key} should be float or None, got {type(val)}"
                )

    def test_n_days_is_int(self, full_fixture):
        returns, labels, *_ = full_fixture
        out = regime_conditional_analysis(returns, labels)
        for regime in KNOWN_REGIMES:
            assert isinstance(out[regime]["n_days"], int)
