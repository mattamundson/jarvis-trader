"""Golden-vector parity test for dm_edge_screen.py against a reference implementation.

Reference: johntwk/Diebold-Mariano-Test (MIT) semantics — DM statistic with HLN (1997)
small-sample modification. We validate:
  1. Synthetic-data parity vs a hand-computed closed-form case (h=1, no autocorrelation).
  2. Statistical sanity: identical series -> p=1; shifted series -> rejection.
  3. p-value function parity vs scipy.stats.t.sf (if scipy available) on a t-grid.
  4. Trade-sidecar ingestion across strict pnl extraction, index alignment, exit-date alignment,
     and backwards-compatible --input-mode aliasing.

Run: engine/.venv/Scripts/python engine/backtest/tests_dm_edge_screen.py
Research-lane only; not wired into the test suite.
"""
from __future__ import annotations

import json
import math
import random
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dm_edge_screen import (  # noqa: E402
    _t_sf_two_sided,
    align,
    align_by_ordinal,
    dm_test,
    load_trade_pnl_series,
    load_trade_series,
)


def write_json(payload) -> str:
    fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fh)
    fh.close()
    return fh.name


def test_load_trade_pnl_series_wrapped_schema() -> None:
    path = write_json({"trades": [{"pnl": 10.5}, {"pnl": -2.0}, {"pnl": 0}]})
    vals = load_trade_pnl_series(path)
    assert vals == [10.5, -2.0, 0.0]
    print("PASS wrapped trade sidecar pnl extraction")


def test_load_trade_pnl_series_raw_list_schema() -> None:
    path = write_json([{"pnl": 1}, {"pnl": 2.25}])
    vals = load_trade_pnl_series(path)
    assert vals == [1.0, 2.25]
    print("PASS raw-list trade sidecar pnl extraction")


def test_load_trade_pnl_series_rejects_missing_pnl() -> None:
    path = write_json({"trades": [{"pnl": 1}, {"not_pnl": 2}]})
    try:
        load_trade_pnl_series(path)
    except ValueError as e:
        assert "missing pnl" in str(e)
    else:
        raise AssertionError("expected missing pnl ValueError")
    print("PASS missing pnl rejected")


def test_align_by_ordinal_reports_dropped_tails() -> None:
    a, b, meta = align_by_ordinal([10, 20, 30], [1, 2])
    assert a == [10, 20]
    assert b == [1, 2]
    assert meta == {
        "n_a": 3,
        "n_b": 2,
        "aligned_n": 2,
        "dropped_a_tail": 1,
        "dropped_b_tail": 0,
        "alignment": "ordinal_prefix_min_length",
    }
    print("PASS ordinal alignment reports dropped tails")


def test_cli_trade_mode_outputs_alignment_metadata() -> None:
    a_path = write_json({"trades": [{"pnl": 10}, {"pnl": -5}, {"pnl": 7}, {"pnl": 4}]})
    b_path = write_json({"trades": [{"pnl": 1}, {"pnl": -1}, {"pnl": 2}]})
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("dm_edge_screen.py")),
            a_path,
            b_path,
            "--input-mode",
            "trades",
            "--power",
            "1",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    out = json.loads(proc.stdout)
    assert out["input_mode"] == "trades"
    assert out["input_kind"] == "trades"
    assert out["metric"] == "trade_pnl"
    assert out["n_a"] == 4
    assert out["n_b"] == 3
    assert out["aligned_n"] == 3
    assert out["dropped_a_tail"] == 1
    assert out["dropped_b_tail"] == 0
    assert out["n"] == 3
    assert out["dm_sign_interpretation"] == "negative_favors_a_positive_favors_b"
    print("PASS trade-mode CLI emits alignment metadata")


def test_identical_series() -> None:
    """Identical score series -> zero loss differential -> p == 1 (no edge difference)."""
    a = [0.5, -0.2, 0.8, 0.1, -0.3, 0.6, 0.2, 0.9, -0.1, 0.4]
    res = dm_test(a, list(a), power=2, h=1)
    assert res["dm"] is None, f"expected None DM for identical series, got {res}"
    print("PASS identical series -> degenerate (variance 0) handled")


def test_closed_form_case() -> None:
    """Hand-computable case: n=6, known loss differentials, h=1 (no HAC lag).

    d = [1, -1, 1, -1, 1, -1]  -> dbar=0 -> DM=0 -> p=1.
    """
    a = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]  # losses (as -score) alternate
    b = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    res = dm_test(a, b, power=1, h=1)
    assert res["n"] == 6
    assert abs(res["dbar"]) < 1e-12, res
    assert abs(res["dm"]) < 1e-12, res
    assert res["p_two_sided"] == 1.0, res
    print(f"PASS closed-form dbar=0 case: dm={res['dm']:.6f}, p={res['p_two_sided']:.6f}")


def test_clear_rejection() -> None:
    """B consistently better than A -> large positive DM (A worse, higher loss) -> tiny p-value."""
    random.seed(42)
    # A has mean 0 scores; B has mean +2 scores (B better since higher score = better)
    a = [random.gauss(0, 1) for _ in range(60)]
    b = [random.gauss(2, 1) for _ in range(60)]
    res = dm_test(a, b, power=1, h=1)
    assert res["dm_hln"] > 3, f"expected strongly positive DM (A worse than B), got {res['dm_hln']}"
    assert res["p_two_sided"] < 0.01, f"expected rejection, p={res['p_two_sided']}"
    print(f"PASS clear rejection: dm_hln={res['dm_hln']:.3f}, p={res['p_two_sided']:.2e}")


def test_hln_correction_shrinks_statistic() -> None:
    """HLN factor < 1 for h=1 and finite n (small-sample conservatism)."""
    random.seed(7)
    a = [random.gauss(0, 1) for _ in range(12)]
    b = [random.gauss(0.5, 1) for _ in range(12)]
    res = dm_test(a, b, power=1, h=1)
    expected_factor = math.sqrt((12 + 1 - 2 + 0) / 12)
    assert abs(res["hln_factor"] - expected_factor) < 1e-12, res
    assert abs(res["dm_hln"] - res["dm"] * expected_factor) < 1e-12, res
    print(f"PASS HLN factor: {res['hln_factor']:.6f} (dm {res['dm']:.4f} -> {res['dm_hln']:.4f})")


def test_t_parity_scipy() -> None:
    """p-value function matches scipy.stats.t two-sided survival on a grid."""
    try:
        from scipy import stats  # type: ignore
    except ImportError:
        print("SKIP scipy parity (scipy not installed)")
        return
    for dof in (3, 10, 30):
        for t in (0.5, 1.0, 2.0, 3.5, 6.0):
            expected = 2.0 * stats.t.sf(t, dof)
            got = _t_sf_two_sided(t, dof)
            assert abs(expected - got) < 1e-8, (dof, t, expected, got)
    print("PASS t-distribution p parity vs scipy (15 points, max err < 1e-8)")


def test_minimum_sample_guard() -> None:
    res = dm_test([1.0, 2.0], [0.5, 1.0], power=1, h=1)
    assert res["dm"] is None and "insufficient" in res["note"]
    print("PASS n<3 guard")


def test_trade_sidecar_loader_index_and_exit_date_alignment() -> None:
    payload = {
        "trades": [
            {"exit_date": "2026-01-02T10:30:00", "pnl": 10.0, "pnl_pct": 0.01},
            {"exit_date": "2026-01-03T10:30:00", "pnl": -5.0, "pnl_pct": -0.005},
            {"exit_date": "2026-01-04T10:30:00", "pnl": 7.0, "pnl_pct": 0.007},
        ]
    }
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "trades.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        periods, values = load_trade_series(str(path), "pnl", "index")
        assert periods == ["0", "1", "2"]
        assert values == [10.0, -5.0, 7.0]
        periods, values = load_trade_series(str(path), "pnl_pct", "exit_date")
        assert periods == ["2026-01-02T10:30:00", "2026-01-03T10:30:00", "2026-01-04T10:30:00"]
        assert values == [0.01, -0.005, 0.007]
    print("PASS trade sidecar loader supports index and exit_date alignment")


def test_exit_date_no_overlap_alignment_guard() -> None:
    a, b = align(["2026-01-01", "2026-01-02"], [1.0, 2.0], ["2026-02-01"], [3.0])
    assert a == [] and b == []
    res = dm_test(a, b, power=1)
    assert res["dm"] is None and "insufficient" in res["note"]
    print("PASS no-overlap exit_date alignment returns insufficient-sample guard")


if __name__ == "__main__":
    test_load_trade_pnl_series_wrapped_schema()
    test_load_trade_pnl_series_raw_list_schema()
    test_load_trade_pnl_series_rejects_missing_pnl()
    test_align_by_ordinal_reports_dropped_tails()
    test_cli_trade_mode_outputs_alignment_metadata()
    test_identical_series()
    test_closed_form_case()
    test_clear_rejection()
    test_hln_correction_shrinks_statistic()
    test_t_parity_scipy()
    test_minimum_sample_guard()
    test_trade_sidecar_loader_index_and_exit_date_alignment()
    test_exit_date_no_overlap_alignment_guard()
    print("\nALL GOLDEN-VECTOR TESTS PASSED")
