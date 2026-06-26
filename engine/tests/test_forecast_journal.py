"""Tests for the morning forecast journal (Phase C). Uses a temp DB."""

import json

import pytest

from analysis.forecast_journal import (
    get_forecast,
    list_journal,
    update_outcome,
    upsert_forecast,
    write_json_backup,
)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "journal_test.db"


_LEVELS = {"symbol": "ES", "pivot": 100.0, "r1": 110.0, "s1": 90.0, "targets_up": [101.0]}
_READ = {"bias": "bearish", "conviction": 0.6, "narrative": "liquidity reset feel"}


def test_upsert_then_get_roundtrip(db):
    upsert_forecast("2026-06-25", "ES", _LEVELS, "2026-06-25T08:00:00Z", read=_READ, db_path=db)
    row = get_forecast("2026-06-25", "ES", db_path=db)
    assert row is not None
    assert row["symbol"] == "ES"
    assert row["levels"]["pivot"] == 100.0
    assert row["read"]["bias"] == "bearish"
    assert row["conviction"] == pytest.approx(0.6)
    assert row["read_bias"] == "bearish"
    # outcome side still empty
    assert row["actual_close"] is None
    assert row["read_brier"] is None


def test_upsert_is_idempotent_and_preserves_outcome(db):
    upsert_forecast("2026-06-25", "ES", _LEVELS, "2026-06-25T08:00:00Z", read=_READ, db_path=db)
    # score it
    update_outcome(
        "2026-06-25",
        "ES",
        {"open": 100, "high": 105, "low": 95, "close": 98},
        "2026-06-25T21:00:00Z",
        level_scores={"pivot_touched": True},
        read_score=1.0,
        read_brier=0.16,
        db_path=db,
    )
    # re-run the morning brief (re-upsert) — must NOT wipe the outcome
    upsert_forecast("2026-06-25", "ES", _LEVELS, "2026-06-25T08:05:00Z", read=_READ, db_path=db)
    row = get_forecast("2026-06-25", "ES", db_path=db)
    assert row["actual_close"] == 98
    assert row["read_brier"] == pytest.approx(0.16)
    assert row["forecast_ts"] == "2026-06-25T08:05:00Z"  # forecast side did update


def test_update_outcome_returns_false_when_no_row(db):
    ok = update_outcome(
        "2026-06-25",
        "NQ",
        {"open": 1, "high": 2, "low": 0, "close": 1},
        "2026-06-25T21:00:00Z",
        db_path=db,
    )
    assert ok is False


def test_list_journal_date_range(db):
    for d in ("2026-06-23", "2026-06-24", "2026-06-25"):
        upsert_forecast(d, "ES", _LEVELS, f"{d}T08:00:00Z", db_path=db)
    rows = list_journal("2026-06-24", "2026-06-25", db_path=db)
    assert [r["date"] for r in rows] == ["2026-06-24", "2026-06-25"]


def test_get_missing_returns_none(db):
    assert get_forecast("2026-06-25", "MGC", db_path=db) is None


def test_forecast_without_read_has_null_read(db):
    upsert_forecast("2026-06-25", "MGC", _LEVELS, "2026-06-25T08:00:00Z", db_path=db)
    row = get_forecast("2026-06-25", "MGC", db_path=db)
    assert row["read"] is None
    assert row["conviction"] is None


def test_json_backup_written(tmp_path):
    payload = {"date": "2026-06-25", "symbols": {"ES": _LEVELS}}
    path = write_json_backup("2026-06-25", payload, json_dir=tmp_path)
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["symbols"]["ES"]["pivot"] == 100.0
