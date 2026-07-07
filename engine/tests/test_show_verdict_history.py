"""Tests for show_verdict_history — portfolio-wide gate v2 dashboard.

Validates JSON parsing, sorting, filtering, and the days-until-expiry
calculation that gates downstream cron alerts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backtest import show_verdict_history as svh

# ---------------------------------------------------------- #
# Helpers                                                    #
# ---------------------------------------------------------- #


def _write_verdict(
    dir_: Path,
    *,
    symbol: str,
    family: str = "trend",
    rank: int = 1,
    verdict: str = "PASS",
    passed_via: str | None = "alt",
    age_days: float = 1.0,
    extra_metrics: dict | None = None,
    archived: bool = False,
) -> Path:
    """Write a verdict JSON file and return its path."""
    target_dir = dir_ / "archive" if archived else dir_
    target_dir.mkdir(parents=True, exist_ok=True)
    created = (datetime.now(tz=timezone.utc) - timedelta(days=age_days)).isoformat()
    metrics = {
        "pf_ci_lower": 2.0,
        "p_edge": 0.75,
        "mc_95th_dd_pct": 1.0,
        "dsr": 1.0,
        "wfo_consistency": "STRONG",
        "fixed_params_min_pf": 1.35,
        "cost_survives_through": "catastrophic",
    }
    if extra_metrics:
        metrics.update(extra_metrics)
    doc = {
        "symbol": symbol,
        "family": family,
        "rank": rank,
        "verdict": verdict,
        "passed_via": passed_via,
        "core_verdict": "PASS" if verdict == "PASS" else "FAIL",
        "alt_verdict": "PASS" if passed_via == "alt" else "FAIL",
        "n_core_passed": 4 if verdict == "PASS" else 1,
        "n_alt_passed": 5 if verdict == "PASS" else 0,
        "created_at": created,
        "gate_v2_metrics": metrics,
        "wfo_config": {
            "n_oos_windows": 18,
            "n_oos_windows_with_trades": 12,
            "total_oos_trades": 50,
        },
    }
    path = target_dir / f"{symbol}_{family}_rank{rank}.json"
    path.write_text(json.dumps(doc))
    return path


@pytest.fixture
def tmp_verdicts_dir(tmp_path, monkeypatch):
    """Point svh.VERDICTS_DIR to an isolated tmp dir."""
    monkeypatch.setattr(svh, "VERDICTS_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------- #
# _load_verdict                                              #
# ---------------------------------------------------------- #


def test_load_verdict_returns_none_for_missing_file(tmp_verdicts_dir):
    assert svh._load_verdict(tmp_verdicts_dir / "missing.json") is None


def test_load_verdict_returns_none_for_empty_file(tmp_verdicts_dir):
    p = tmp_verdicts_dir / "empty.json"
    p.write_text("")
    assert svh._load_verdict(p) is None


def test_load_verdict_returns_none_for_malformed_json(tmp_verdicts_dir):
    p = tmp_verdicts_dir / "bad.json"
    p.write_text("{not valid json")
    assert svh._load_verdict(p) is None


def test_load_verdict_succeeds_for_well_formed(tmp_verdicts_dir):
    p = _write_verdict(tmp_verdicts_dir, symbol="MES")
    v = svh._load_verdict(p)
    assert v is not None
    assert v["symbol"] == "MES"


# ---------------------------------------------------------- #
# _summarize                                                 #
# ---------------------------------------------------------- #


def test_summarize_extracts_key_fields(tmp_verdicts_dir):
    p = _write_verdict(
        tmp_verdicts_dir, symbol="MGC", verdict="PASS", passed_via="alt", age_days=2.0
    )
    v = svh._load_verdict(p)
    row = svh._summarize(v, p, archived=False)
    assert row["symbol"] == "MGC"
    assert row["verdict"] == "PASS"
    assert row["passed_via"] == "alt"
    assert row["pf_ci_lower"] == 2.0
    assert row["p_edge"] == 0.75
    assert row["dsr"] == 1.0
    assert row["archived"] is False


def test_summarize_computes_days_until_expiry(tmp_verdicts_dir):
    """30-day TTL: a verdict 5 days old has 25 days remaining."""
    p = _write_verdict(tmp_verdicts_dir, symbol="MES", age_days=5.0)
    v = svh._load_verdict(p)
    row = svh._summarize(v, p, archived=False)
    assert 24 <= row["days_until_expiry"] <= 25  # tolerance for clock drift


def test_summarize_negative_days_for_expired(tmp_verdicts_dir):
    p = _write_verdict(tmp_verdicts_dir, symbol="MES", age_days=35.0)
    v = svh._load_verdict(p)
    row = svh._summarize(v, p, archived=False)
    assert row["days_until_expiry"] is not None
    assert row["days_until_expiry"] < 0


# ---------------------------------------------------------- #
# _collect                                                   #
# ---------------------------------------------------------- #


def test_collect_walks_active_dir(tmp_verdicts_dir):
    _write_verdict(tmp_verdicts_dir, symbol="MES")
    _write_verdict(tmp_verdicts_dir, symbol="MGC", rank=4)
    rows = svh._collect(include_archive=False)
    assert len(rows) == 2
    assert {r["symbol"] for r in rows} == {"MES", "MGC"}


def test_collect_excludes_archive_by_default(tmp_verdicts_dir):
    _write_verdict(tmp_verdicts_dir, symbol="MES")
    _write_verdict(tmp_verdicts_dir, symbol="OLD", archived=True)
    rows = svh._collect(include_archive=False)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "MES"


def test_collect_includes_archive_when_requested(tmp_verdicts_dir):
    _write_verdict(tmp_verdicts_dir, symbol="MES")
    _write_verdict(tmp_verdicts_dir, symbol="OLD", archived=True)
    rows = svh._collect(include_archive=True)
    assert len(rows) == 2
    assert {r["archived"] for r in rows} == {True, False}


def test_collect_skips_unparseable_files(tmp_verdicts_dir):
    _write_verdict(tmp_verdicts_dir, symbol="MES")
    (tmp_verdicts_dir / "broken.json").write_text("{bad")
    rows = svh._collect(include_archive=False)
    assert len(rows) == 1


# ---------------------------------------------------------- #
# _sort_key — PASS first, then by symbol/family/rank         #
# ---------------------------------------------------------- #


def test_sort_puts_pass_before_fail(tmp_verdicts_dir):
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="FAIL", passed_via=None)
    _write_verdict(tmp_verdicts_dir, symbol="MGC", verdict="PASS")
    rows = sorted(svh._collect(include_archive=False), key=svh._sort_key)
    assert rows[0]["verdict"] == "PASS"
    assert rows[1]["verdict"] == "FAIL"


def test_sort_groups_pass_by_symbol(tmp_verdicts_dir):
    _write_verdict(tmp_verdicts_dir, symbol="MGC", verdict="PASS")
    _write_verdict(tmp_verdicts_dir, symbol="MES", verdict="PASS")
    rows = sorted(svh._collect(include_archive=False), key=svh._sort_key)
    assert rows[0]["symbol"] == "MES"  # alphabetic
    assert rows[1]["symbol"] == "MGC"


# ---------------------------------------------------------- #
# Format helpers                                             #
# ---------------------------------------------------------- #


def test_format_metric_handles_none():
    assert svh._format_metric(None) == "  -  "


def test_format_metric_handles_nan():
    assert svh._format_metric(float("nan")) == "NaN"


def test_format_metric_rounds_to_places():
    assert svh._format_metric(1.23456, 2) == "1.23"


def test_format_metric_passes_through_strings():
    assert svh._format_metric("STRONG") == "STRONG"
