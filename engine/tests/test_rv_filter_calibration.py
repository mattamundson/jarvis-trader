"""Tests for the report-only RV-filter calibration counter.

The counter must accurately track live-trade progress toward the enable
threshold and must never itself enable/disable anything — these tests cover the
counting/threshold logic only (no config or filter state is touched).
"""
import pytest

from analytics.rv_filter_calibration import (
    DEFAULT_MIN_TRADES,
    RV_FILTER_TARGETS,
    RVFilterTarget,
    calibration_status,
    compute_status,
    format_report,
    status_from_db,
)


class TestComputeStatus:
    def _target(self, min_trades=60):
        return RVFilterTarget("MGC", 9.0, min_trades, "note")

    def test_partial_progress(self):
        s = compute_status(15, self._target(60))
        assert s.closed_trades == 15
        assert s.remaining == 45
        assert s.progress_pct == 25.0
        assert s.ready is False

    def test_ready_at_threshold(self):
        s = compute_status(60, self._target(60))
        assert s.remaining == 0
        assert s.progress_pct == 100.0
        assert s.ready is True

    def test_over_threshold_caps_progress_and_remaining(self):
        s = compute_status(75, self._target(60))
        assert s.remaining == 0
        assert s.progress_pct == 100.0
        assert s.ready is True

    def test_negative_count_clamped(self):
        s = compute_status(-5, self._target(60))
        assert s.closed_trades == 0
        assert s.remaining == 60
        assert s.ready is False

    def test_carries_rv_metadata(self):
        s = compute_status(10, self._target())
        assert s.min_rv_annualized == 9.0


class TestCalibrationStatus:
    def test_uses_injected_counter_for_all_targets(self):
        counts = {"MGC": 40, "MES": 61}
        statuses = calibration_status(lambda sym: counts[sym])
        by_symbol = {s.symbol: s for s in statuses}
        assert set(by_symbol) == set(RV_FILTER_TARGETS)
        assert by_symbol["MGC"].ready is False and by_symbol["MGC"].remaining == 20
        assert by_symbol["MES"].ready is True

    def test_counter_exception_is_isolated_as_zero(self):
        def counter(sym):
            if sym == "MGC":
                raise RuntimeError("db down")
            return 60

        by_symbol = {s.symbol: s for s in calibration_status(counter)}
        assert by_symbol["MGC"].closed_trades == 0  # failure -> 0, not a crash
        assert by_symbol["MES"].ready is True

    def test_default_threshold_is_60(self):
        assert DEFAULT_MIN_TRADES == 60
        assert all(t.min_trades == 60 for t in RV_FILTER_TARGETS.values())


class TestStatusFromDb:
    def test_counts_closed_trades_readonly(self):
        calls = []

        class FakeDb:
            def get_closed_trades(self, symbol=None, limit=500):
                calls.append((symbol, limit))
                return [{"id": i} for i in range({"MGC": 12, "MES": 60}[symbol])]

        statuses = {s.symbol: s for s in status_from_db(FakeDb())}
        assert statuses["MGC"].closed_trades == 12
        assert statuses["MES"].ready is True
        # Only read calls were made — one per target.
        assert sorted(c[0] for c in calls) == ["MES", "MGC"]


class TestFormatReport:
    def test_human_readable_lines(self):
        report = format_report(calibration_status(lambda s: 30))
        assert "RV-filter calibration" in report
        assert "MGC" in report and "MES" in report
        assert "to go" in report  # 30/60 -> not ready

    def test_empty(self):
        assert "no targets" in format_report([])
