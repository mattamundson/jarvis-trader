"""[safety-review] PR-10: DSR gate in ValidationMetrics._compute().

Two duplicated Sharpe calculators annualized a tiny daily-P&L sample with no
minimum-sample-size gate and no ceiling, producing an implausible PASS
(observed ann_sharpe=3.436 on a handful of days). The Deflated Sharpe Ratio
already existed (backtest.deflated_sharpe) but was report-only, never wired
into a live go/no-go decision.

At n_trials=1 (live paper trading is one strategy under observation, not a
grid search), DSR's own max-bias correction term is zero, so DSR alone
floors near 0.5 for any near-zero-or-positive raw Sharpe and will NOT reject
a short lucky streak by itself -- verified empirically below. The minimum
daily-observation floor (mirrors backtest._gate_v2_helpers.
MIN_OOS_TRADES_PER_WINDOW) is what actually blocks it; both checks are
required together.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from analytics.validation_metrics import TARGETS, ValidationMetrics
from backtest._gate_v2_helpers import GATE_DSR, MIN_OOS_TRADES_PER_WINDOW
from backtest.deflated_sharpe import deflated_sharpe_from_returns


def _trades_from_daily_pnls(daily_pnls: list[float]) -> list[dict]:
    """One closed trade per calendar day, each day's PnL as given."""
    base = datetime(2026, 6, 1, 14, 30)
    return [
        {
            "entry_time": (base + timedelta(days=i)).isoformat() + "Z",
            "exit_time": (base + timedelta(days=i, hours=1)).isoformat() + "Z",
            "pnl": pnl,
        }
        for i, pnl in enumerate(daily_pnls)
    ]


class TestDailyReturnsSharedBucketing:
    def test_daily_returns_matches_direct_bucketing(self):
        """_daily_returns() feeds both _compute_sharpe and _compute_dsr the
        identical series -- DSR's math assumes matching sharpe/n_obs inputs."""
        vm = ValidationMetrics()
        trades = _trades_from_daily_pnls([40.0, 10.0, -5.0, 30.0])
        returns = vm._daily_returns(trades)
        assert sorted(returns) == sorted([40.0, 10.0, -5.0, 30.0])


class TestDsrMatchesDirectCall:
    def test_compute_dsr_matches_deflated_sharpe_from_returns(self):
        vm = ValidationMetrics()
        daily = [80.0, -60.0, 90.0, -50.0, 70.0, -40.0, 60.0]
        trades = _trades_from_daily_pnls(daily)

        wired = vm._compute_dsr(trades)
        direct = deflated_sharpe_from_returns(daily, n_trials=1)

        assert wired["dsr"] == direct["dsr"]
        assert wired["n_obs"] == direct["n_obs"] == len(daily)


class TestDsrAloneCannotRejectShortLuckyStreak:
    """Pins the exact reasoning that motivated the n_obs floor: without it,
    DSR at n_trials=1 would have let the incident shape through."""

    def test_two_observation_lucky_streak_passes_dsr_alone(self):
        r = deflated_sharpe_from_returns([40.0, 10.0], n_trials=1)
        assert r["dsr"] >= GATE_DSR  # DSR alone says PASS
        assert r["n_obs"] < MIN_OOS_TRADES_PER_WINDOW  # but the sample is too thin to trust


class TestValidationMetricsDsrGate:
    def test_short_lucky_streak_blocked_by_n_obs_floor(self):
        """2 trading days, ann_sharpe far above min_sharpe (old gate would
        PASS) -- the combined DSR+n_obs gate must FAIL."""
        vm = ValidationMetrics()
        trades = _trades_from_daily_pnls([40.0, 10.0])

        dsr_result = vm._compute_dsr(trades)
        assert dsr_result["n_obs"] == 2 < TARGETS["min_dsr_n_obs"]

        # Reproduce the exact boolean the _compute() method assigns to
        # targets_met["dsr_0_10"], since it needs a live DB connection to
        # exercise end-to-end.
        dsr_0_10 = (
            dsr_result["dsr"] >= TARGETS["min_dsr"]
            and dsr_result["n_obs"] >= TARGETS["min_dsr_n_obs"]
        )
        assert dsr_0_10 is False

    def test_solid_longer_track_record_passes_dsr_gate(self):
        """40 trading days, low variance, consistently positive -- must PASS."""
        vm = ValidationMetrics()
        daily = [80.0 + (i % 3) * 5 for i in range(40)]
        trades = _trades_from_daily_pnls(daily)

        dsr_result = vm._compute_dsr(trades)
        assert dsr_result["n_obs"] == 40 >= TARGETS["min_dsr_n_obs"]
        assert dsr_result["dsr"] >= TARGETS["min_dsr"]

        dsr_0_10 = (
            dsr_result["dsr"] >= TARGETS["min_dsr"]
            and dsr_result["n_obs"] >= TARGETS["min_dsr_n_obs"]
        )
        assert dsr_0_10 is True

    def test_targets_dict_exposes_dsr_floor_and_n_obs_floor(self):
        assert TARGETS["min_dsr"] == GATE_DSR
        assert TARGETS["min_dsr_n_obs"] == MIN_OOS_TRADES_PER_WINDOW

    def test_compute_dsr_none_for_single_trade(self):
        """< 2 observations -- deflated_sharpe_from_returns returns the
        degenerate zero-DSR shape, never a spurious pass."""
        vm = ValidationMetrics()
        trades = _trades_from_daily_pnls([100.0])
        result = vm._compute_dsr(trades)
        assert result["dsr"] == 0.0
        assert result["n_obs"] == 1
