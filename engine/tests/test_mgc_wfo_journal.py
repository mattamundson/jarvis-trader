"""Tests for backtest/mgc_wfo_journal.py (P2-8).

Verifies that the MGC WFO journal correctly parses gate_v2 verdict files,
writes a CSV with the expected columns, deduplicates on append, and
handles edge cases (Infinity values, missing fields, non-MGC files).
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from backtest.mgc_wfo_journal import (
    _CSV_FIELDNAMES,
    append_verdict,
    collect_all_mgc_rows,
    parse_verdict_file,
    read_journal,
    rebuild_journal,
)

# ---------------------------------------------------------------------------
# Fixtures — minimal synthetic verdict dicts
# ---------------------------------------------------------------------------


def _make_verdict(
    *,
    symbol: str = "MGC",
    family: str = "trend",
    rank: int = 4,
    verdict: str = "PASS",
    passed_via: str = "alt",
    p_edge: float = 0.68,
    wfo_consistency: str = "MODERATE",
    pf_ci_lower: float = 2.60,
    dsr: float = 1.0,
    mc_95th_dd_pct: float = 1.24,
    n_oos_windows: int = 19,
    total_oos_trades: int = 67,
    created_at: str = "2026-05-21T09:01:28.932112+00:00",
) -> dict:
    return {
        "symbol": symbol,
        "family": family,
        "rank": rank,
        "verdict": verdict,
        "passed_via": passed_via,
        "created_at": created_at,
        "gate_v2": {"verdict": verdict, "passed_via": passed_via},
        "gate_v2_metrics": {
            "p_edge": p_edge,
            "wfo_consistency": wfo_consistency,
            "pf_ci_lower": pf_ci_lower,
            "dsr": dsr,
            "mc_95th_dd_pct": mc_95th_dd_pct,
        },
        "wfo_config": {
            "n_oos_windows": n_oos_windows,
            "total_oos_trades": total_oos_trades,
        },
    }


def _write_verdict(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# parse_verdict_file
# ---------------------------------------------------------------------------


def test_parse_returns_none_for_non_mgc(tmp_path: Path) -> None:
    f = tmp_path / "MES_trend_rank1.json"
    _write_verdict(f, _make_verdict(symbol="MES"))
    assert parse_verdict_file(f) is None


def test_parse_returns_row_for_mgc(tmp_path: Path) -> None:
    f = tmp_path / "MGC_trend_rank4.json"
    _write_verdict(f, _make_verdict())
    row = parse_verdict_file(f)
    assert row is not None
    assert row["symbol"] == "MGC"
    assert row["verdict"] == "PASS"
    assert row["passed_via"] == "alt"
    assert row["p_edge"] == "0.68"
    assert row["wfo_consistency"] == "MODERATE"


def test_parse_handles_infinity_in_json(tmp_path: Path) -> None:
    """Bare Infinity in WFO window oos_pf must not crash the parser."""
    data = _make_verdict()
    raw = json.dumps(data).replace('"pf_ci_lower": 2.6', '"pf_ci_lower": Infinity')
    f = tmp_path / "MGC_trend_rank_inf.json"
    f.write_text(raw, encoding="utf-8")
    row = parse_verdict_file(f)
    assert row is not None
    # Infinity should map to empty string
    assert row["pf_ci_lower"] == ""


def test_parse_handles_nan_metrics(tmp_path: Path) -> None:
    """NaN values in metrics should map to empty string."""
    data = _make_verdict(pf_ci_lower=float("nan"))
    f = tmp_path / "MGC_trend_rank_nan.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    row = parse_verdict_file(f)
    assert row is not None
    assert row["pf_ci_lower"] == ""


def test_parse_missing_gate_v2_metrics(tmp_path: Path) -> None:
    """File without gate_v2_metrics key should still parse, metrics → empty."""
    data = _make_verdict()
    del data["gate_v2_metrics"]
    f = tmp_path / "MGC_trend_rank_no_metrics.json"
    _write_verdict(f, data)
    row = parse_verdict_file(f)
    assert row is not None
    assert row["p_edge"] == ""
    assert row["wfo_consistency"] == ""


def test_parse_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert parse_verdict_file(tmp_path / "nonexistent.json") is None


# ---------------------------------------------------------------------------
# collect_all_mgc_rows
# ---------------------------------------------------------------------------


def test_collect_scans_current_and_archive(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()

    _write_verdict(
        tmp_path / "MGC_trend_rank4.json",
        _make_verdict(created_at="2026-05-21T09:00:00+00:00"),
    )
    _write_verdict(
        archive / "MGC_trend_rank3.json",
        _make_verdict(rank=3, verdict="FAIL", created_at="2026-05-06T06:56:31+00:00"),
    )
    _write_verdict(
        tmp_path / "MES_trend_rank11.json",  # non-MGC — should be ignored
        _make_verdict(symbol="MES"),
    )

    rows = collect_all_mgc_rows(tmp_path)
    assert len(rows) == 2
    # sorted by run_date: rank3 (older) first
    assert rows[0]["rank"] == "3"
    assert rows[1]["rank"] == "4"


def test_collect_returns_empty_when_no_mgc_files(tmp_path: Path) -> None:
    _write_verdict(tmp_path / "MES_trend_rank1.json", _make_verdict(symbol="MES"))
    assert collect_all_mgc_rows(tmp_path) == []


# ---------------------------------------------------------------------------
# rebuild_journal
# ---------------------------------------------------------------------------


def test_rebuild_writes_csv_with_correct_columns(tmp_path: Path) -> None:
    _write_verdict(tmp_path / "MGC_trend_rank4.json", _make_verdict())
    journal = tmp_path / "journal.csv"

    n = rebuild_journal(journal_path=journal, verdicts_dir=tmp_path)
    assert n == 1

    rows = read_journal(journal)
    assert len(rows) == 1
    assert set(rows[0].keys()) == set(_CSV_FIELDNAMES)


def test_rebuild_overwrites_existing_journal(tmp_path: Path) -> None:
    _write_verdict(tmp_path / "MGC_trend_rank4.json", _make_verdict())
    journal = tmp_path / "journal.csv"

    rebuild_journal(journal_path=journal, verdicts_dir=tmp_path)
    rebuild_journal(journal_path=journal, verdicts_dir=tmp_path)

    rows = read_journal(journal)
    assert len(rows) == 1  # not doubled


# ---------------------------------------------------------------------------
# append_verdict
# ---------------------------------------------------------------------------


def test_append_adds_new_row(tmp_path: Path) -> None:
    f = tmp_path / "MGC_trend_rank4.json"
    _write_verdict(f, _make_verdict())
    journal = tmp_path / "journal.csv"

    result = append_verdict(f, journal_path=journal)
    assert result is True
    assert len(read_journal(journal)) == 1


def test_append_deduplicates_same_file(tmp_path: Path) -> None:
    f = tmp_path / "MGC_trend_rank4.json"
    _write_verdict(f, _make_verdict())
    journal = tmp_path / "journal.csv"

    append_verdict(f, journal_path=journal)
    result = append_verdict(f, journal_path=journal)
    assert result is False  # not appended again
    assert len(read_journal(journal)) == 1


def test_append_returns_false_for_non_mgc(tmp_path: Path) -> None:
    f = tmp_path / "MES_trend_rank1.json"
    _write_verdict(f, _make_verdict(symbol="MES"))
    journal = tmp_path / "journal.csv"
    assert append_verdict(f, journal_path=journal) is False


def test_append_creates_journal_if_missing(tmp_path: Path) -> None:
    f = tmp_path / "MGC_trend_rank4.json"
    _write_verdict(f, _make_verdict())
    journal = tmp_path / "new_journal.csv"
    assert not journal.exists()

    append_verdict(f, journal_path=journal)
    assert journal.exists()
    rows = read_journal(journal)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "MGC"


# ---------------------------------------------------------------------------
# read_journal
# ---------------------------------------------------------------------------


def test_read_journal_returns_empty_list_when_missing(tmp_path: Path) -> None:
    assert read_journal(tmp_path / "nonexistent.csv") == []


def test_read_journal_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "MGC_trend_rank4.json"
    _write_verdict(f, _make_verdict(p_edge=0.6842, mc_95th_dd_pct=1.2386))
    journal = tmp_path / "journal.csv"
    rebuild_journal(journal_path=journal, verdicts_dir=tmp_path)

    rows = read_journal(journal)
    assert rows[0]["p_edge"] == "0.6842"
    assert rows[0]["mc_95th_dd_pct"] == "1.2386"
    assert rows[0]["source_file"] == "MGC_trend_rank4.json"
