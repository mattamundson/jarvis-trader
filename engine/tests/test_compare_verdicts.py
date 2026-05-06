"""Tests for compare_verdicts — gate v2 verdict diff for refresh workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtest import compare_verdicts as cv


def _make_verdict(
    *,
    symbol: str = "MES",
    family: str = "trend",
    rank: int = 11,
    verdict: str = "PASS",
    passed_via: str | None = "alt",
    champion: dict | None = None,
    metrics: dict | None = None,
    total_oos_trades: int = 16,
) -> dict:
    """Build a minimal verdict dict for tests."""
    return {
        "symbol": symbol,
        "family": family,
        "rank": rank,
        "verdict": verdict,
        "passed_via": passed_via,
        "champion_params": champion or {"fast": 60, "slow": 200, "atr_trail_mult": 2.0},
        "gate_v2_metrics": metrics
        or {
            "pf_ci_lower": 2.156,
            "p_edge": 0.75,
            "dsr": 1.0,
            "mc_95th_dd_pct": 0.81,
            "fixed_params_min_pf": 1.35,
            "wfo_consistency": "STRONG",
            "cost_survives_through": "catastrophic",
        },
        "wfo_config": {"total_oos_trades": total_oos_trades},
    }


# ---------------------------------------------------------- #
# No-drift case                                              #
# ---------------------------------------------------------- #


def test_compare_no_drift_returns_no_review_needed():
    old = _make_verdict()
    new = _make_verdict()
    diff = cv.compare(old, new)
    assert diff["needs_review"] is False
    assert diff["verdict_transition"] == "no transition"
    assert diff["champion_drift"] == []


# ---------------------------------------------------------- #
# Verdict transitions                                        #
# ---------------------------------------------------------- #


def test_compare_pass_to_fail_flagged():
    old = _make_verdict(verdict="PASS")
    new = _make_verdict(verdict="FAIL", passed_via=None)
    diff = cv.compare(old, new)
    assert diff["verdict_transition"] == "PASS -> FAIL"
    assert diff["needs_review"] is True


def test_compare_fail_to_pass_flagged():
    old = _make_verdict(verdict="FAIL", passed_via=None)
    new = _make_verdict(verdict="PASS")
    diff = cv.compare(old, new)
    assert diff["verdict_transition"] == "FAIL -> PASS"
    assert diff["needs_review"] is True


def test_compare_alt_to_core_path_change_flagged():
    """Same PASS but path changed (alt → core indicates the strategy got STRONGER)."""
    old = _make_verdict(verdict="PASS", passed_via="alt")
    new = _make_verdict(verdict="PASS", passed_via="core")
    diff = cv.compare(old, new)
    assert "PASS-alt -> PASS-core" in diff["verdict_transition"]
    assert diff["needs_review"] is True


# ---------------------------------------------------------- #
# Champion drift                                             #
# ---------------------------------------------------------- #


def test_compare_param_under_threshold_not_drifted():
    """5% change is below the 10% threshold."""
    old = _make_verdict(champion={"fast": 60, "slow": 200, "atr_trail_mult": 2.0})
    new = _make_verdict(champion={"fast": 63, "slow": 200, "atr_trail_mult": 2.0})  # +5%
    diff = cv.compare(old, new)
    drift = next(d for d in diff["champion_drift"] if d["param"] == "fast")
    assert drift["exceeds_threshold"] is False
    assert diff["needs_review"] is False


def test_compare_param_over_threshold_flagged():
    """20% change is above the 10% threshold."""
    old = _make_verdict(champion={"fast": 60, "slow": 200, "atr_trail_mult": 2.0})
    new = _make_verdict(champion={"fast": 72, "slow": 200, "atr_trail_mult": 2.0})  # +20%
    diff = cv.compare(old, new)
    drift = next(d for d in diff["champion_drift"] if d["param"] == "fast")
    assert drift["exceeds_threshold"] is True
    assert diff["needs_review"] is True


def test_compare_new_param_appears():
    """A new param in the refreshed verdict should be flagged."""
    old = _make_verdict(champion={"fast": 60, "slow": 200})
    new = _make_verdict(champion={"fast": 60, "slow": 200, "min_rv_annualized": 0.0})
    diff = cv.compare(old, new)
    new_param_drift = next(d for d in diff["champion_drift"] if d["param"] == "min_rv_annualized")
    assert new_param_drift["old"] is None
    assert new_param_drift["new"] == 0.0


# ---------------------------------------------------------- #
# Symbol/family mismatch warnings                            #
# ---------------------------------------------------------- #


def test_compare_symbol_mismatch_emits_warning():
    old = _make_verdict(symbol="MES")
    new = _make_verdict(symbol="MGC")
    diff = cv.compare(old, new)
    assert any("Symbol mismatch" in w for w in diff["warnings"])
    assert diff["needs_review"] is True


def test_compare_family_mismatch_emits_warning():
    old = _make_verdict(family="trend")
    new = _make_verdict(family="orb")
    diff = cv.compare(old, new)
    assert any("Family mismatch" in w for w in diff["warnings"])


# ---------------------------------------------------------- #
# OOS sample-size delta                                      #
# ---------------------------------------------------------- #


def test_compare_oos_delta_computed():
    old = _make_verdict(total_oos_trades=16)
    new = _make_verdict(total_oos_trades=61)
    diff = cv.compare(old, new)
    assert diff["oos_delta"]["delta"] == 45
    assert diff["oos_delta"]["old_total_oos_trades"] == 16
    assert diff["oos_delta"]["new_total_oos_trades"] == 61


# ---------------------------------------------------------- #
# Metric deltas                                              #
# ---------------------------------------------------------- #


def test_compare_metric_deltas_show_numeric_change():
    old = _make_verdict(metrics={"pf_ci_lower": 2.0, "p_edge": 0.75})
    new = _make_verdict(metrics={"pf_ci_lower": 2.5, "p_edge": 0.80})
    diff = cv.compare(old, new)
    assert diff["metric_deltas"]["pf_ci"]["delta"] == 0.5
    assert diff["metric_deltas"]["p_edge"]["delta"] == 0.05


def test_compare_metric_string_change():
    """wfo_consistency goes from STRONG → MODERATE — string change."""
    old = _make_verdict(metrics={"wfo_consistency": "STRONG"})
    new = _make_verdict(metrics={"wfo_consistency": "MODERATE"})
    diff = cv.compare(old, new)
    assert diff["metric_deltas"]["wfo"]["old"] == "STRONG"
    assert diff["metric_deltas"]["wfo"]["new"] == "MODERATE"


# ---------------------------------------------------------- #
# _is_drifted edge cases                                     #
# ---------------------------------------------------------- #


def test_is_drifted_handles_none():
    assert cv._is_drifted(None, 5.0, 0.10) is False
    assert cv._is_drifted(5.0, None, 0.10) is False


def test_is_drifted_handles_zero():
    assert cv._is_drifted(0.0, 0.0, 0.10) is False
    assert cv._is_drifted(0.0, 0.5, 0.10) is True


def test_is_drifted_handles_strings():
    """Non-numeric values are not "drifted" by the threshold check."""
    assert cv._is_drifted("STRONG", "MODERATE", 0.10) is False


# ---------------------------------------------------------- #
# CLI exit code                                              #
# ---------------------------------------------------------- #


def test_compare_writes_json_when_requested(tmp_path: Path, capsys):
    """--json mode must produce parseable JSON on stdout."""
    old_p = tmp_path / "old.json"
    new_p = tmp_path / "new.json"
    old_p.write_text(json.dumps(_make_verdict()))
    new_p.write_text(json.dumps(_make_verdict()))
    import sys

    sys.argv = ["compare_verdicts", str(old_p), str(new_p), "--json"]
    rc = cv.main()
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["verdict_transition"] == "no transition"
    assert rc == 0


def test_compare_returns_exit_2_on_missing_file(tmp_path: Path, capsys):
    """Missing file → stderr error + exit code 2."""
    import sys

    sys.argv = [
        "compare_verdicts",
        str(tmp_path / "missing.json"),
        str(tmp_path / "also_missing.json"),
    ]
    rc = cv.main()
    assert rc == 2


def test_compare_returns_exit_1_when_review_needed(tmp_path: Path, capsys):
    old_p = tmp_path / "old.json"
    new_p = tmp_path / "new.json"
    old_p.write_text(json.dumps(_make_verdict(verdict="PASS")))
    new_p.write_text(json.dumps(_make_verdict(verdict="FAIL", passed_via=None)))
    import sys

    sys.argv = ["compare_verdicts", str(old_p), str(new_p)]
    rc = cv.main()
    assert rc == 1
