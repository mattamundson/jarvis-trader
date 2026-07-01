"""Tests for the OOS access ledger (ml-pitfalls-defense.md pitfall #4)."""

from datetime import datetime, timezone

from engine.analytics.oos_access_ledger import (
    DEFAULT_QUARTERLY_CAP,
    check_oos_budget,
    oos_access_count,
    quarter_key,
    record_oos_access,
)

Q3 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)   # 2026Q3
Q2 = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)  # 2026Q2


def test_quarter_key_boundaries():
    assert quarter_key(datetime(2026, 1, 1, tzinfo=timezone.utc)) == "2026Q1"
    assert quarter_key(datetime(2026, 3, 31, tzinfo=timezone.utc)) == "2026Q1"
    assert quarter_key(datetime(2026, 4, 1, tzinfo=timezone.utc)) == "2026Q2"
    assert quarter_key(datetime(2026, 12, 31, tzinfo=timezone.utc)) == "2026Q4"


def test_record_and_count_within_quarter(tmp_path):
    led = tmp_path / "oos.jsonl"
    for _ in range(2):
        record_oos_access("MES", "optimizer:1h:50iter", now=Q3, ledger_path=led)
    assert oos_access_count("MES", now=Q3, ledger_path=led) == 2
    # A different quarter is isolated.
    assert oos_access_count("MES", now=Q2, ledger_path=led) == 0


def test_symbols_are_isolated(tmp_path):
    led = tmp_path / "oos.jsonl"
    record_oos_access("MES", "c", now=Q3, ledger_path=led)
    record_oos_access("MGC", "c", now=Q3, ledger_path=led)
    assert oos_access_count("MES", now=Q3, ledger_path=led) == 1
    assert oos_access_count("MGC", now=Q3, ledger_path=led) == 1


def test_budget_not_exceeded_under_cap(tmp_path):
    led = tmp_path / "oos.jsonl"
    for _ in range(DEFAULT_QUARTERLY_CAP):
        record_oos_access("MES", "c", now=Q3, ledger_path=led)
    b = check_oos_budget("MES", now=Q3, ledger_path=led)
    assert b["count"] == DEFAULT_QUARTERLY_CAP
    assert b["exceeded"] is False
    assert b["remaining"] == 0


def test_mes_budget_exceeded_over_cap(tmp_path):
    """MES: a 4th campaign this quarter (cap 3) trips the advisory flag."""
    led = tmp_path / "oos.jsonl"
    for _ in range(DEFAULT_QUARTERLY_CAP + 1):
        record_oos_access("MES", "optimizer:1h:50iter", now=Q3, ledger_path=led)
    b = check_oos_budget("MES", now=Q3, ledger_path=led)
    assert b["symbol"] == "MES"
    assert b["quarter"] == "2026Q3"
    assert b["count"] == 4
    assert b["cap"] == 3
    assert b["exceeded"] is True
    assert b["remaining"] == 0


def test_kind_scoping(tmp_path):
    led = tmp_path / "oos.jsonl"
    record_oos_access("MES", "c", kind="campaign", now=Q3, ledger_path=led)
    record_oos_access("MES", "p", kind="promotion", now=Q3, ledger_path=led)
    assert oos_access_count("MES", kind="campaign", now=Q3, ledger_path=led) == 1
    assert oos_access_count("MES", kind="promotion", now=Q3, ledger_path=led) == 1
    assert oos_access_count("MES", now=Q3, ledger_path=led) == 2


def test_missing_ledger_counts_zero(tmp_path):
    led = tmp_path / "does_not_exist.jsonl"
    assert oos_access_count("MES", now=Q3, ledger_path=led) == 0
    assert check_oos_budget("MES", now=Q3, ledger_path=led)["exceeded"] is False


def test_corrupt_line_is_tolerated(tmp_path):
    led = tmp_path / "oos.jsonl"
    record_oos_access("MES", "c", now=Q3, ledger_path=led)
    with open(led, "a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
    record_oos_access("MES", "c", now=Q3, ledger_path=led)
    # The corrupt middle line is skipped, both valid records still counted.
    assert oos_access_count("MES", now=Q3, ledger_path=led) == 2
