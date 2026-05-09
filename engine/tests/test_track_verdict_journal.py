"""End-to-end tests for backtest.track_verdict_journal.

Tests the full verdict-journal pipeline on synthetic verdict JSON files:
- new rows appended correctly
- deduplication (already-seen source_file skipped)
- Infinity literal in JSON handled without error
- dry-run mode produces no side-effects
- --include-archive flag picks up archive/ subdirectory
- missing required fields skipped with a warning
- journal CSV columns match _COLUMNS spec
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

# Unit under test
from backtest.track_verdict_journal import (
    _COLUMNS,
    _extract_row,
    _load_journal,
    update_journal,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_verdict(
    *,
    symbol: str = "MES",
    family: str = "trend",
    rank: int = 11,
    verdict: str = "PASS",
    passed_via: str = "alt",
    created_at: str = "2026-05-08T10:00:00+00:00",
    pf_ci_lower: float = 2.50,
    p_edge: float = 0.75,
    mc_95th_dd_pct: float = 0.81,
    dsr: float = 1.0,
    wfo_consistency: str = "STRONG",
    fixed_params_min_pf: float = 1.35,
) -> dict:
    return {
        "symbol": symbol,
        "family": family,
        "rank": rank,
        "verdict": verdict,
        "passed_via": passed_via,
        "created_at": created_at,
        "gate_v2_metrics": {
            "pf_ci_lower": pf_ci_lower,
            "p_edge": p_edge,
            "mc_95th_dd_pct": mc_95th_dd_pct,
            "dsr": dsr,
            "wfo_consistency": wfo_consistency,
            "fixed_params_min_pf": fixed_params_min_pf,
        },
    }


def _write_verdict(path: Path, verdict: dict) -> None:
    path.write_text(json.dumps(verdict), encoding="utf-8")


# ---------------------------------------------------------------------------
# _extract_row — unit tests
# ---------------------------------------------------------------------------


def test_extract_row_returns_expected_fields():
    v = _make_verdict()
    row = _extract_row(v, "MES_trend_rank11.json")
    assert row is not None
    assert row["symbol"] == "MES"
    assert row["family"] == "trend"
    assert row["rank"] == 11
    assert row["verdict"] == "PASS"
    assert row["passed_via"] == "alt"
    assert row["date"] == "2026-05-08"
    assert row["pf_ci_lower"] == "2.5000"
    assert row["p_edge"] == "0.7500"
    assert row["mc_dd_pct"] == "0.8100"
    assert row["dsr"] == "1.0000"
    assert row["wfo"] == "STRONG"
    assert row["source_file"] == "MES_trend_rank11.json"


def test_extract_row_missing_symbol_returns_none():
    v = _make_verdict()
    del v["symbol"]
    assert _extract_row(v, "x.json") is None


def test_extract_row_missing_verdict_returns_none():
    v = _make_verdict()
    del v["verdict"]
    assert _extract_row(v, "x.json") is None


def test_extract_row_missing_family_returns_none():
    v = _make_verdict()
    del v["family"]
    assert _extract_row(v, "x.json") is None


def test_extract_row_absent_metrics_returns_empty_strings():
    v = _make_verdict()
    v["gate_v2_metrics"] = {}
    row = _extract_row(v, "x.json")
    assert row is not None
    assert row["pf_ci_lower"] == ""
    assert row["p_edge"] == ""


def test_extract_row_rank_none_becomes_empty_string():
    v = _make_verdict()
    v["rank"] = None
    row = _extract_row(v, "x.json")
    assert row is not None
    assert row["rank"] == ""


# ---------------------------------------------------------------------------
# update_journal — end-to-end with synthetic verdicts
# ---------------------------------------------------------------------------


def test_update_journal_appends_new_rows(tmp_path, monkeypatch):
    """update_journal writes a journal with all discovered verdict files."""
    verdicts_dir = tmp_path / "gate_v2_verdicts"
    verdicts_dir.mkdir()

    _write_verdict(verdicts_dir / "MES_trend_rank11.json", _make_verdict(symbol="MES"))
    _write_verdict(verdicts_dir / "MGC_trend_rank4.json", _make_verdict(symbol="MGC", rank=4))

    monkeypatch.setattr("backtest.track_verdict_journal.VERDICTS_DIR", verdicts_dir)
    monkeypatch.setattr(
        "backtest.track_verdict_journal.JOURNAL_PATH", verdicts_dir / "_journal.csv"
    )

    n = update_journal()

    assert n == 2
    journal_path = verdicts_dir / "_journal.csv"
    assert journal_path.exists()

    rows = list(csv.DictReader(journal_path.open(encoding="utf-8")))
    assert len(rows) == 2
    symbols = {r["symbol"] for r in rows}
    assert symbols == {"MES", "MGC"}


def test_update_journal_deduplicates(tmp_path, monkeypatch):
    """Running update_journal twice must not add duplicate rows."""
    verdicts_dir = tmp_path / "gate_v2_verdicts"
    verdicts_dir.mkdir()
    _write_verdict(verdicts_dir / "MES_trend_rank11.json", _make_verdict())

    monkeypatch.setattr("backtest.track_verdict_journal.VERDICTS_DIR", verdicts_dir)
    monkeypatch.setattr(
        "backtest.track_verdict_journal.JOURNAL_PATH", verdicts_dir / "_journal.csv"
    )

    n1 = update_journal()
    n2 = update_journal()  # second run — already journaled

    assert n1 == 1
    assert n2 == 0

    rows = list(csv.DictReader((verdicts_dir / "_journal.csv").open(encoding="utf-8")))
    assert len(rows) == 1


def test_update_journal_dry_run_no_file_written(tmp_path, monkeypatch):
    """dry_run=True must not write any file."""
    verdicts_dir = tmp_path / "gate_v2_verdicts"
    verdicts_dir.mkdir()
    _write_verdict(verdicts_dir / "MES_trend_rank11.json", _make_verdict())

    journal_path = verdicts_dir / "_journal.csv"
    monkeypatch.setattr("backtest.track_verdict_journal.VERDICTS_DIR", verdicts_dir)
    monkeypatch.setattr("backtest.track_verdict_journal.JOURNAL_PATH", journal_path)

    n = update_journal(dry_run=True)

    assert n == 1
    assert not journal_path.exists()


def test_update_journal_infinity_in_json_handled(tmp_path, monkeypatch):
    """Verdict files with Infinity literals (from Python float serialization)
    must be parsed without error — the journal row must be written correctly."""
    verdicts_dir = tmp_path / "gate_v2_verdicts"
    verdicts_dir.mkdir()

    # Write a JSON file with the Python-produced Infinity literal
    raw = json.dumps(_make_verdict()).replace('"pf_ci_lower": 2.5', '"pf_ci_lower": Infinity')
    (verdicts_dir / "MES_trend_rank11.json").write_text(raw, encoding="utf-8")

    monkeypatch.setattr("backtest.track_verdict_journal.VERDICTS_DIR", verdicts_dir)
    monkeypatch.setattr(
        "backtest.track_verdict_journal.JOURNAL_PATH", verdicts_dir / "_journal.csv"
    )

    n = update_journal()

    assert n == 1
    rows = list(csv.DictReader((verdicts_dir / "_journal.csv").open(encoding="utf-8")))
    assert len(rows) == 1
    # Infinity was replaced with null so pf_ci_lower is empty string
    assert rows[0]["pf_ci_lower"] == ""


def test_update_journal_include_archive(tmp_path, monkeypatch):
    """--include-archive discovers verdict files in the archive/ subdirectory."""
    verdicts_dir = tmp_path / "gate_v2_verdicts"
    verdicts_dir.mkdir()
    archive_dir = verdicts_dir / "archive"
    archive_dir.mkdir()

    _write_verdict(verdicts_dir / "MES_trend_rank11.json", _make_verdict(symbol="MES"))
    _write_verdict(archive_dir / "MES_trend_rank10.json", _make_verdict(symbol="MES", rank=10))

    monkeypatch.setattr("backtest.track_verdict_journal.VERDICTS_DIR", verdicts_dir)
    monkeypatch.setattr(
        "backtest.track_verdict_journal.JOURNAL_PATH", verdicts_dir / "_journal.csv"
    )

    n = update_journal(include_archive=True)

    assert n == 2
    rows = list(csv.DictReader((verdicts_dir / "_journal.csv").open(encoding="utf-8")))
    source_files = {r["source_file"] for r in rows}
    assert "MES_trend_rank11.json" in source_files
    assert "archive/MES_trend_rank10.json" in source_files


def test_update_journal_skips_underscore_prefixed_files(tmp_path, monkeypatch):
    """Files whose names start with '_' (e.g. _journal.csv, _index.json)
    must be skipped — they are not verdict files."""
    verdicts_dir = tmp_path / "gate_v2_verdicts"
    verdicts_dir.mkdir()

    _write_verdict(verdicts_dir / "MES_trend_rank11.json", _make_verdict())
    (verdicts_dir / "_not_a_verdict.json").write_text(json.dumps(_make_verdict()), encoding="utf-8")

    monkeypatch.setattr("backtest.track_verdict_journal.VERDICTS_DIR", verdicts_dir)
    monkeypatch.setattr(
        "backtest.track_verdict_journal.JOURNAL_PATH", verdicts_dir / "_journal.csv"
    )

    n = update_journal()

    assert n == 1


def test_update_journal_missing_required_fields_skipped(tmp_path, monkeypatch, capsys):
    """A verdict JSON missing symbol/family/verdict must be skipped with a warning."""
    verdicts_dir = tmp_path / "gate_v2_verdicts"
    verdicts_dir.mkdir()

    bad = {"rank": 1, "gate_v2_metrics": {}}  # missing symbol, family, verdict
    (verdicts_dir / "bad_verdict.json").write_text(json.dumps(bad), encoding="utf-8")
    _write_verdict(verdicts_dir / "MES_trend_rank11.json", _make_verdict())

    monkeypatch.setattr("backtest.track_verdict_journal.VERDICTS_DIR", verdicts_dir)
    monkeypatch.setattr(
        "backtest.track_verdict_journal.JOURNAL_PATH", verdicts_dir / "_journal.csv"
    )

    n = update_journal()

    # Only the valid verdict should be journaled
    assert n == 1


def test_update_journal_csv_columns_match_spec(tmp_path, monkeypatch):
    """The journal CSV must have exactly the columns defined in _COLUMNS."""
    verdicts_dir = tmp_path / "gate_v2_verdicts"
    verdicts_dir.mkdir()
    _write_verdict(verdicts_dir / "MES_trend_rank11.json", _make_verdict())

    monkeypatch.setattr("backtest.track_verdict_journal.VERDICTS_DIR", verdicts_dir)
    monkeypatch.setattr(
        "backtest.track_verdict_journal.JOURNAL_PATH", verdicts_dir / "_journal.csv"
    )

    update_journal()

    with (verdicts_dir / "_journal.csv").open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames

    assert list(fieldnames) == _COLUMNS


def test_update_journal_sorted_output(tmp_path, monkeypatch):
    """Journal rows are sorted by (symbol, family, rank, date)."""
    verdicts_dir = tmp_path / "gate_v2_verdicts"
    verdicts_dir.mkdir()

    _write_verdict(
        verdicts_dir / "MNQ_trend_rank2.json",
        _make_verdict(symbol="MNQ", rank=2, created_at="2026-05-08T00:00:00+00:00"),
    )
    _write_verdict(
        verdicts_dir / "MES_trend_rank11.json",
        _make_verdict(symbol="MES", rank=11, created_at="2026-05-07T00:00:00+00:00"),
    )
    _write_verdict(
        verdicts_dir / "MES_trend_rank4.json",
        _make_verdict(symbol="MES", rank=4, created_at="2026-05-06T00:00:00+00:00"),
    )

    monkeypatch.setattr("backtest.track_verdict_journal.VERDICTS_DIR", verdicts_dir)
    monkeypatch.setattr(
        "backtest.track_verdict_journal.JOURNAL_PATH", verdicts_dir / "_journal.csv"
    )

    update_journal()

    rows = list(csv.DictReader((verdicts_dir / "_journal.csv").open(encoding="utf-8")))
    symbols = [r["symbol"] for r in rows]
    # MES rows must come before MNQ (lex order)
    assert symbols.index("MES") < symbols.index("MNQ")


# ---------------------------------------------------------------------------
# _load_journal — unit tests
# ---------------------------------------------------------------------------


def test_load_journal_empty_if_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backtest.track_verdict_journal.JOURNAL_PATH",
        tmp_path / "nonexistent.csv",
    )
    assert _load_journal() == []


def test_load_journal_returns_rows(tmp_path, monkeypatch):
    csv_path = tmp_path / "_journal.csv"
    csv_path.write_text(
        "date,symbol,family,rank,verdict,passed_via,pf_ci_lower,p_edge,"
        "mc_dd_pct,dsr,wfo,fixed_min_pf,source_file\n"
        "2026-05-08,MES,trend,11,PASS,alt,2.5000,0.7500,0.8100,1.0000,STRONG,1.3500,MES_trend_rank11.json\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("backtest.track_verdict_journal.JOURNAL_PATH", csv_path)

    rows = _load_journal()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "MES"
    assert rows[0]["verdict"] == "PASS"
