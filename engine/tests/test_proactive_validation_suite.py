"""
Regression tests for the proactive validation suite integrity fixes
(engine/routers/proactive_validation_router.py).

Covers three defects that made /validate/proactive-suite OVERSTATE readiness:

  1. Gate-pass truthiness bug — `_check_validation_gates` counted each pass_fail
     entry as passing because a non-empty dict is always truthy, so a losing PF
     still read "6/6 passing" and status="pass".
  2. Hard-fail key mismatch — the count/days shortfall exclusion used the gate
     keys (min_trades/min_days) instead of the pass_fail keys
     (total_trades/days_active), escalating normal accrual to a blocking fail.
  3. WFE PF-mislabel — `_check_wfe` read a weekly PROFIT FACTOR from wfe_snapshots
     and compared it against 0–1 WFE-ratio thresholds (0.50/0.30), which
     coincidentally rubber-stamped losing weeks (PF 0.55 >= 0.50 read "healthy").
"""

from __future__ import annotations

import pytest

from routers import proactive_validation_router as pv
from routers.proactive_validation_router import (
    _WEEKLY_PF_BREAKEVEN,
    _WEEKLY_PF_HEALTHY,
    _check_recent_weekly_pf,
    _check_validation_gates,
)


def _gate(value, threshold, passes):
    """Build one pass_fail entry in ValidationTracker._get_pass_fail shape."""
    return {"value": value, "threshold": threshold, "passes": passes}


def _progress(*, pf_pass, sharpe_pass, wr_pass, trades_pass, days_pass, dd_pass,
              profit_factor=2.5):
    """Construct a get_progress()-shaped dict with explicit per-gate pass flags."""
    return {
        "instrument": "MES",
        "profit_factor": profit_factor,
        "sharpe_ratio": 1.6,
        "win_rate_pct": 56.0,
        "max_drawdown_pct": 8.0,
        "pass_fail": {
            "profit_factor": _gate(profit_factor, 2.0, pf_pass),
            "sharpe_ratio": _gate(1.6, 1.5, sharpe_pass),
            "win_rate_pct": _gate(56.0, 55.0, wr_pass),
            "total_trades": _gate(60, 60, trades_pass),
            "days_active": _gate(31, 30, days_pass),
            "max_drawdown_pct": _gate(8.0, 15.0, dd_pass),
        },
    }


class TestValidationGatesPassCounting:
    """Defect 1 + 2: gate-pass truthiness and hard-fail key mismatch."""

    def test_all_gates_passing_returns_pass(self):
        prog = _progress(pf_pass=True, sharpe_pass=True, wr_pass=True,
                         trades_pass=True, days_pass=True, dd_pass=True)
        check = _check_validation_gates(prog)
        assert check.status == "pass"
        assert "6/6" in check.value

    def test_losing_pf_is_not_counted_as_passing(self):
        """REGRESSION: PF below threshold must drop the passing count and FAIL.

        Pre-fix, `sum(1 for v in pf.values() if v)` counted the non-empty PF dict
        as truthy, so a losing strategy still read "6/6 passing" / status=pass.
        """
        prog = _progress(pf_pass=False, sharpe_pass=True, wr_pass=True,
                         trades_pass=True, days_pass=True, dd_pass=True,
                         profit_factor=0.55)
        check = _check_validation_gates(prog)
        assert check.status == "fail", "a failing PF gate must yield status=fail"
        assert "5/6" in check.value, "the failing gate must not be counted as passing"

    def test_hard_metric_fail_is_fail_not_warn(self):
        """A drawdown breach (hard metric) must be a blocking fail."""
        prog = _progress(pf_pass=True, sharpe_pass=True, wr_pass=True,
                         trades_pass=True, days_pass=True, dd_pass=False)
        check = _check_validation_gates(prog)
        assert check.status == "fail"

    def test_count_and_days_shortfall_is_warn_not_fail(self):
        """REGRESSION: a pure trade-count/days shortfall is accrual, not failure.

        Pre-fix, the exclusion list used gate-config keys (min_trades/min_days)
        which never matched the pass_fail keys (total_trades/days_active), so a
        strategy meeting every METRIC gate but short on sample was wrongly
        escalated to a blocking fail.
        """
        prog = _progress(pf_pass=True, sharpe_pass=True, wr_pass=True,
                         trades_pass=False, days_pass=False, dd_pass=True)
        check = _check_validation_gates(prog)
        assert check.status == "warn", "count/days shortfall alone must warn, not fail"

    def test_not_started_is_insufficient_data(self):
        check = _check_validation_gates({"status": "not_started"})
        assert check.status == "insufficient_data"

    def test_uses_real_validation_tracker_shape(self):
        """Shape-drift guard: feed a real ValidationTracker progress dict.

        Empty tracker -> all gates fail (0 trades) -> not 'pass'. Confirms
        _check_validation_gates consumes the live pass_fail contract, so a future
        change to _get_pass_fail's shape breaks this test instead of silently
        reverting to the truthiness bug.
        """
        from paper.validation_tracker import ValidationTracker

        prog = ValidationTracker(data_dir="data").get_progress("MES")
        check = _check_validation_gates(prog)
        # Real empty tracker is either not_started or a non-pass status — never "pass".
        assert check.status != "pass"


class TestRecentWeeklyPF:
    """Defect 3: weekly profit factor judged on the PF scale, not WFE-ratio scale."""

    def test_no_snapshot_is_insufficient_data(self, monkeypatch):
        monkeypatch.setattr(pv, "_load_latest_weekly_pf", lambda s: None)
        check = _check_recent_weekly_pf("MES")
        assert check.status == "insufficient_data"
        assert check.name == "Recent Weekly PF"

    def test_losing_weekly_pf_fails(self, monkeypatch):
        """REGRESSION: PF 0.55 is a losing week and must FAIL.

        Pre-fix it was compared against the WFE warn threshold 0.50, so 0.55 >=
        0.50 read "WFE healthy" — a losing strategy stamped pass.
        """
        monkeypatch.setattr(pv, "_load_latest_weekly_pf", lambda s: 0.55)
        check = _check_recent_weekly_pf("MES")
        assert check.status == "fail"
        assert _WEEKLY_PF_BREAKEVEN == 1.0

    def test_marginal_weekly_pf_warns(self, monkeypatch):
        monkeypatch.setattr(pv, "_load_latest_weekly_pf", lambda s: 1.1)
        check = _check_recent_weekly_pf("MES")
        assert check.status == "warn"

    def test_healthy_weekly_pf_passes(self, monkeypatch):
        monkeypatch.setattr(pv, "_load_latest_weekly_pf", lambda s: 2.0)
        check = _check_recent_weekly_pf("MES")
        assert check.status == "pass"
        assert _WEEKLY_PF_HEALTHY == pytest.approx(1.3)

    def test_breakeven_boundary_is_warn(self, monkeypatch):
        """PF exactly at breakeven (1.0) is the bottom of the warn band, not fail."""
        monkeypatch.setattr(pv, "_load_latest_weekly_pf", lambda s: 1.0)
        check = _check_recent_weekly_pf("MES")
        assert check.status == "warn"
