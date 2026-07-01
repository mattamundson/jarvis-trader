"""Tests for the OOS access ledger (analytics/oos_access_ledger.py).

Uses a tmp ledger file and fixed instants (module never calls now() itself).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from analytics.oos_access_ledger import (
    quarter_access_count,
    quarter_label,
    record_oos_access,
)

Q3 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
Q4 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def test_quarter_label():
    assert quarter_label(datetime(2026, 1, 15, tzinfo=timezone.utc)) == "2026Q1"
    assert quarter_label(datetime(2026, 7, 1, tzinfo=timezone.utc)) == "2026Q3"
    assert quarter_label(datetime(2026, 12, 31, tzinfo=timezone.utc)) == "2026Q4"


def test_records_and_counts(tmp_path):
    ledger = tmp_path / "log.jsonl"
    assert quarter_access_count("MES", "2026Q3", ledger=ledger) == 0
    record_oos_access("MES", "promotion", now=Q3, ledger=ledger)
    record_oos_access("MES", "promotion", now=Q3, ledger=ledger)
    assert quarter_access_count("MES", "2026Q3", ledger=ledger) == 2


def test_counter_is_per_symbol_and_per_quarter(tmp_path):
    ledger = tmp_path / "log.jsonl"
    record_oos_access("MES", "p", now=Q3, ledger=ledger)
    record_oos_access("MGC", "p", now=Q3, ledger=ledger)
    record_oos_access("MES", "p", now=Q4, ledger=ledger)
    assert quarter_access_count("MES", "2026Q3", ledger=ledger) == 1
    assert quarter_access_count("MGC", "2026Q3", ledger=ledger) == 1
    assert quarter_access_count("MES", "2026Q4", ledger=ledger) == 1


def test_warn_only_default_never_blocks(tmp_path):
    ledger = tmp_path / "log.jsonl"
    last = None
    for _ in range(5):  # cap default 3
        last = record_oos_access("MES", "p", now=Q3, cap=3, ledger=ledger)
    assert last.count_this_quarter == 5
    assert last.over_cap is True
    assert last.enforced is False
    assert last.allowed is True  # warn-only: recorded but not blocked


def test_enforce_blocks_over_cap(tmp_path):
    ledger = tmp_path / "log.jsonl"
    results = [
        record_oos_access("MES", "p", now=Q3, cap=2, enforce=True, ledger=ledger)
        for _ in range(4)
    ]
    assert [r.allowed for r in results] == [True, True, False, False]
    assert results[2].over_cap is True


def test_requires_explicit_now(tmp_path):
    with pytest.raises(ValueError):
        record_oos_access("MES", "p", ledger=tmp_path / "log.jsonl")


def test_tolerates_foreign_lines_in_shared_log(tmp_path):
    ledger = tmp_path / "log.jsonl"
    ledger.write_text('{"kind":"optimization_iteration","score":0.5}\nnot json\n')
    record_oos_access("MES", "p", now=Q3, ledger=ledger)
    assert quarter_access_count("MES", "2026Q3", ledger=ledger) == 1
