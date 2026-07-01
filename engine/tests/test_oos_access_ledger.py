"""Tests for the OOS-access ledger + contamination cap (research-integrity guard).

All tests use an isolated ledger file under tmp_path and an injected clock, so
they never touch the real engine/data ledger.
"""
from datetime import datetime, timezone

import pytest

from analytics.oos_access_ledger import (
    DEFAULT_OOS_ACCESS_CAP,
    BudgetStatus,
    OOSBudgetExceeded,
    budget_status,
    count_accesses,
    quarter_of,
    record_access,
    record_if_within_budget,
)


def _dt(month: int, day: int = 1) -> datetime:
    return datetime(2026, month, day, 12, 0, tzinfo=timezone.utc)


def _ledger(tmp_path) -> str:
    return str(tmp_path / "oos.jsonl")


class TestQuarterOf:
    @pytest.mark.parametrize(
        "month,expected",
        [(1, "2026Q1"), (3, "2026Q1"), (4, "2026Q2"), (7, "2026Q3"), (12, "2026Q4")],
    )
    def test_quarter_boundaries(self, month, expected):
        assert quarter_of(_dt(month)) == expected


class TestRecordAndCount:
    def test_record_then_count(self, tmp_path):
        led = _ledger(tmp_path)
        record_access("promote MGC", ledger_path=led, now=_dt(7))
        record_access("promote MES", ledger_path=led, now=_dt(8))
        assert count_accesses("2026Q3", ledger_path=led) == 2
        assert count_accesses("2026Q2", ledger_path=led) == 0

    def test_count_isolates_by_dataset(self, tmp_path):
        led = _ledger(tmp_path)
        record_access("a", ledger_path=led, now=_dt(7))
        record_access("b", dataset="other_oos", ledger_path=led, now=_dt(7))
        assert count_accesses("2026Q3", ledger_path=led) == 1  # default dataset only
        assert count_accesses("2026Q3", dataset="other_oos", ledger_path=led) == 1

    def test_record_returns_stamped_record(self, tmp_path):
        rec = record_access("x", ledger_path=_ledger(tmp_path), now=_dt(7), extra={"symbol": "MGC"})
        assert rec["quarter"] == "2026Q3"
        assert rec["dataset"] == "2025_oos"  # DEFAULT_DATASET
        assert rec["purpose"] == "x"
        assert rec["symbol"] == "MGC"

    def test_missing_ledger_counts_zero(self, tmp_path):
        assert count_accesses("2026Q3", ledger_path=_ledger(tmp_path)) == 0


class TestBudgetStatus:
    def test_defaults_to_current_quarter(self, tmp_path):
        led = _ledger(tmp_path)
        s = budget_status(ledger_path=led, now=_dt(7))
        assert isinstance(s, BudgetStatus)
        assert s.quarter == "2026Q3"
        assert s.cap == DEFAULT_OOS_ACCESS_CAP
        assert s.used == 0 and s.remaining == DEFAULT_OOS_ACCESS_CAP and s.exceeded is False

    def test_exceeded_at_cap(self, tmp_path):
        led = _ledger(tmp_path)
        for i in range(DEFAULT_OOS_ACCESS_CAP):
            record_access(f"p{i}", ledger_path=led, now=_dt(7))
        s = budget_status(ledger_path=led, now=_dt(7))
        assert s.used == DEFAULT_OOS_ACCESS_CAP
        assert s.remaining == 0
        assert s.exceeded is True


class TestRecordIfWithinBudget:
    def test_allows_up_to_cap_then_raises(self, tmp_path):
        led = _ledger(tmp_path)
        for i in range(DEFAULT_OOS_ACCESS_CAP):
            record_if_within_budget(f"p{i}", ledger_path=led, now=_dt(7))
        with pytest.raises(OOSBudgetExceeded):
            record_if_within_budget("over", ledger_path=led, now=_dt(7))
        # The denied access was NOT recorded.
        assert count_accesses("2026Q3", ledger_path=led) == DEFAULT_OOS_ACCESS_CAP

    def test_budget_resets_next_quarter(self, tmp_path):
        led = _ledger(tmp_path)
        for i in range(DEFAULT_OOS_ACCESS_CAP):
            record_if_within_budget(f"p{i}", ledger_path=led, now=_dt(7))  # Q3 full
        # A new quarter has fresh budget.
        rec = record_if_within_budget("new-quarter", ledger_path=led, now=_dt(10), cap=DEFAULT_OOS_ACCESS_CAP)
        assert rec["quarter"] == "2026Q4"
        assert count_accesses("2026Q4", ledger_path=led) == 1

    def test_custom_cap(self, tmp_path):
        led = _ledger(tmp_path)
        record_if_within_budget("p0", ledger_path=led, now=_dt(7), cap=1)
        with pytest.raises(OOSBudgetExceeded):
            record_if_within_budget("p1", ledger_path=led, now=_dt(7), cap=1)
