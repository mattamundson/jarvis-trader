"""Tests for family-wide BH-FDR over the gate-v2 campaign (backtest/family_fdr.py)."""

from __future__ import annotations

import math

from backtest import family_fdr as ff

# --- bh_fdr core -----------------------------------------------------------


def test_bh_fdr_empty():
    assert ff.bh_fdr([], 0.10) == []


def test_bh_fdr_all_tiny_pass():
    # All p-values far below any BH line -> all discoveries.
    flags = ff.bh_fdr([0.0, 1e-6, 1e-5], 0.10)
    assert flags == [True, True, True]


def test_bh_fdr_all_large_fail():
    flags = ff.bh_fdr([0.6, 0.7, 0.9, 0.99], 0.10)
    assert flags == [False, False, False, False]


def test_bh_fdr_known_vector():
    # Classic BH worked example. n=4, q=0.10 -> only p=0.001 survives.
    pvals = [0.001, 0.20, 0.40, 0.80]
    flags = ff.bh_fdr(pvals, 0.10)
    assert flags == [True, False, False, False]


def test_bh_fdr_step_up_includes_lower_ranks():
    # BH is step-up: if a higher rank passes, all lower-p entries pass too even
    # if an individual lower rank sat just above its own line.
    # p=[0.01,0.02,0.03,0.04,0.05], n=5, q=0.10 lines=[.02,.04,.06,.08,.10]
    # largest k meeting p<=line: rank5 (0.05<=0.10) -> cutoff 0.05 -> all pass.
    flags = ff.bh_fdr([0.01, 0.02, 0.03, 0.04, 0.05], 0.10)
    assert flags == [True, True, True, True, True]


def test_bh_fdr_preserves_input_order():
    # Unsorted input: flags must map back to original positions.
    pvals = [0.80, 0.001, 0.40]
    flags = ff.bh_fdr(pvals, 0.10)
    assert flags == [False, True, False]


# --- binomial OOS sign-test -----------------------------------------------


def test_binomial_perfect_small():
    # 7/7 profitable windows -> P(X>=7 | Bin(7,0.5)) = 1/128.
    assert math.isclose(ff.binomial_oos_pvalue(1.0, 7), 1 / 128, rel_tol=1e-9)


def test_binomial_coin_flip():
    # 3/5 profitable -> P(X>=3 | Bin(5,0.5)) = (10+5+1)/32 = 0.5.
    assert math.isclose(ff.binomial_oos_pvalue(0.6, 5), 0.5, rel_tol=1e-9)


def test_binomial_zero_windows_is_one():
    assert ff.binomial_oos_pvalue(0.9, 0) == 1.0


def test_binomial_monotonic_in_k():
    # More profitable windows -> smaller (more significant) p-value.
    p_low = ff.binomial_oos_pvalue(0.4, 10)
    p_high = ff.binomial_oos_pvalue(0.9, 10)
    assert p_high < p_low


# --- conservative / shrink-only properties ---------------------------------


def _synthetic_verdicts():
    """Two strong + two weak strategies, plus one with no OOS data."""

    def mk(_id, verdict, p_edge, n, dsr, pf):
        return {
            "_id": _id,
            "symbol": _id.split("_")[0],
            "family": "trend",
            "verdict": verdict,
            "gate_v2_metrics": {
                "pf_ci_lower": pf,
                "p_edge": p_edge,
                "dsr": dsr,
            },
            "wfo_config": {"n_oos_windows": n},
        }

    return [
        mk("AAA_trend#1", "PASS", 1.0, 7, 1.0, 3.0),
        mk("BBB_trend#1", "PASS", 0.68, 19, 1.0, 2.5),
        mk("CCC_gap#1", "FAIL", 0.4, 5, 0.0, 0.5),
        mk("DDD_ib#1", "FAIL", 0.0, 5, 0.0, 0.4),
        # no OOS windows -> excluded
        {
            "_id": "EEE_meanrev#1",
            "symbol": "EEE",
            "family": "meanrev",
            "verdict": "FAIL",
            "gate_v2_metrics": {"p_edge": None, "dsr": None},
            "wfo_config": {"n_oos_windows": 0},
        },
    ]


def test_build_family_excludes_no_oos():
    family, excluded = ff.build_family(_synthetic_verdicts())
    ids = {r["id"] for r in family}
    assert "EEE_meanrev#1" not in ids
    assert len(excluded) == 1
    assert excluded[0]["id"] == "EEE_meanrev#1"


def test_robust_edge_is_subset_of_gate_pass(monkeypatch):
    monkeypatch.setattr(ff, "load_verdicts", lambda *a, **k: _synthetic_verdicts())
    report = ff.run(q=0.10)
    robust = set(report["robust_edge_ids"])
    gate_pass = set(report["gate_pass_ids"])
    # FDR can only shrink: every robust edge must be a gate-v2 PASS.
    assert robust.issubset(gate_pass)


def test_run_counts_consistent(monkeypatch):
    monkeypatch.setattr(ff, "load_verdicts", lambda *a, **k: _synthetic_verdicts())
    report = ff.run(q=0.10)
    assert report["n_verdicts_total"] == 5
    assert report["n_family"] == 4
    assert report["n_excluded"] == 1
    assert report["n_robust_edge"] <= report["n_gate_pass"]


def test_run_on_real_verdicts_smoke():
    # Runs against the live verdict dir; must not crash and must shrink-only.
    # The verdict dir is runtime-generated (empty in a fresh checkout / CI), so
    # assert robustness + the shrink-only invariant, not a minimum count.
    report = ff.run(q=0.10)
    assert report["n_verdicts_total"] >= 0
    assert report["n_robust_edge"] <= report["n_gate_pass"]
    assert set(report["robust_edge_ids"]).issubset(set(report["gate_pass_ids"]))


# --- CPCV verdicts excluded from the sign-test family ----------------------


def test_build_family_excludes_cpcv_verdicts():
    # A CPCV verdict reports many overlapping folds as "windows" -- not
    # independent, so it must be excluded from the binomial sign-test family
    # rather than over-credited alongside sequential-WFO verdicts.
    cpcv_verdict = {
        "_id": "MGC_singlefinder_fill_cpcv",
        "verdict": "PASS",
        "symbol": "MGC",
        "family": "singlefinder_fill",
        "wfo_config": {"cv_method": "cpcv", "n_oos_windows": 15},
        "gate_v2_metrics": {"p_edge": 0.73, "pf_ci_lower": 1.2, "dsr": 0.4},
    }
    seq_verdict = {
        "_id": "MGC_singlefinder_fill_rank1",
        "verdict": "PASS",
        "symbol": "MGC",
        "family": "singlefinder_fill",
        "wfo_config": {"n_oos_windows": 5},
        "gate_v2_metrics": {"p_edge": 0.6, "pf_ci_lower": 1.05, "dsr": 0.2},
    }
    family, excluded = ff.build_family([cpcv_verdict, seq_verdict])
    fam_ids = {r["id"] for r in family}
    exc_ids = {e["id"] for e in excluded}
    assert "MGC_singlefinder_fill_cpcv" in exc_ids
    assert "MGC_singlefinder_fill_cpcv" not in fam_ids
    assert "MGC_singlefinder_fill_rank1" in fam_ids  # sequential stays in the family
    cpcv_reason = next(e["reason"] for e in excluded if e["id"] == "MGC_singlefinder_fill_cpcv")
    assert "overlap" in cpcv_reason.lower()


# --- sample-adequacy: small-sample mirages cannot be robust edges ----------


def _verdict(_id, verdict, p_edge, n, dsr, pf, oos_trades=None):
    wfo = {"n_oos_windows": n}
    if oos_trades is not None:
        wfo["total_oos_trades"] = oos_trades
    return {
        "_id": _id,
        "symbol": _id.split("_")[0],
        "family": "trend",
        "verdict": verdict,
        "gate_v2_metrics": {"pf_ci_lower": pf, "p_edge": p_edge, "dsr": dsr},
        "wfo_config": wfo,
    }


def test_build_family_tags_sample_adequacy():
    # total_oos_trades >= floor -> adequate; below -> inadequate; absent -> unknown.
    v_ok = _verdict("AAA_trend#1", "PASS", 1.0, 7, 1.0, 3.0, oos_trades=67)
    v_thin = _verdict("BBB_trend#1", "PASS", 1.0, 7, 1.0, 3.0, oos_trades=26)
    v_unknown = _verdict("CCC_trend#1", "PASS", 1.0, 7, 1.0, 3.0)  # no total_oos_trades
    family, _ = ff.build_family([v_ok, v_thin, v_unknown])
    by = {r["id"]: r for r in family}
    assert by["AAA_trend#1"]["total_oos_trades"] == 67
    assert by["AAA_trend#1"]["sample_adequate"] is True
    assert by["BBB_trend#1"]["total_oos_trades"] == 26
    assert by["BBB_trend#1"]["sample_adequate"] is False
    assert by["CCC_trend#1"]["total_oos_trades"] is None
    assert by["CCC_trend#1"]["sample_adequate"] is None


def test_sample_inadequate_strategy_not_robust_even_if_bh_significant(monkeypatch):
    # 7/7 OOS PASS clears the BH line in a 1-member family, but 26 < 30 OOS
    # trades is a small-sample mirage (PF 295/inf on 2-trade windows) -> it must
    # NOT be certified a robust edge. This is MGC_trend_rv_filter_rank1.
    v = _verdict("MGC_trend_rv_filter_rank1", "PASS", 1.0, 7, 1.0, 3.18, oos_trades=26)
    monkeypatch.setattr(ff, "load_verdicts", lambda *a, **k: [v])
    report = ff.run(q=0.10)
    row = report["family"][0]
    assert row["bh_significant_binom"] is True  # clears BH on the p-value alone
    assert row["sample_adequate"] is False
    assert row["robust_edge"] is False  # but blocked by sample adequacy
    assert report["n_robust_edge"] == 0


def test_sample_adequate_strong_strategy_can_be_robust(monkeypatch):
    # Same significance, but 40 >= 30 OOS trades -> adequacy does not over-block.
    v = _verdict("AAA_trend#1", "PASS", 1.0, 7, 1.0, 3.18, oos_trades=40)
    monkeypatch.setattr(ff, "load_verdicts", lambda *a, **k: [v])
    report = ff.run(q=0.10)
    row = report["family"][0]
    assert row["bh_significant_binom"] is True
    assert row["sample_adequate"] is True
    assert row["robust_edge"] is True
    assert report["n_robust_edge"] == 1


# --- append_history ledger -------------------------------------------------

import json  # noqa: E402


def _sample_report():
    return {
        "q": 0.10,
        "n_verdicts_total": 7,
        "n_family": 5,
        "n_gate_pass": 2,
        "n_robust_edge": 1,
        "robust_edge_ids": ["MGC_trend_rank4"],
        "extra_ignored_field": "should not appear in the ledger record",
    }


def test_append_history_writes_expected_record(tmp_path):
    path = str(tmp_path / "family_fdr_history.jsonl")
    rec = ff.append_history(_sample_report(), path=path, ts="2026-06-17T00:00:00+00:00")
    assert rec["ts"] == "2026-06-17T00:00:00+00:00"
    assert rec["n_robust_edge"] == 1
    assert rec["robust_edge_ids"] == ["MGC_trend_rank4"]
    # Compact record: only the tracked keys, never the full report.
    assert set(rec.keys()) == {
        "ts",
        "q",
        "n_verdicts_total",
        "n_family",
        "n_gate_pass",
        "n_robust_edge",
        "robust_edge_ids",
    }
    on_disk = json.loads(
        (tmp_path / "family_fdr_history.jsonl").read_text(encoding="utf-8").strip()
    )
    assert on_disk == rec


def test_append_history_is_append_only(tmp_path):
    path = str(tmp_path / "family_fdr_history.jsonl")
    ff.append_history(_sample_report(), path=path, ts="2026-06-17T00:00:00+00:00")
    ff.append_history(_sample_report(), path=path, ts="2026-06-18T00:00:00+00:00")
    lines = (tmp_path / "family_fdr_history.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["ts"] == "2026-06-17T00:00:00+00:00"
    assert json.loads(lines[1])["ts"] == "2026-06-18T00:00:00+00:00"


def test_append_history_creates_parent_dir(tmp_path):
    path = str(tmp_path / "nested" / "sub" / "history.jsonl")
    ff.append_history(_sample_report(), path=path, ts="2026-06-17T00:00:00+00:00")
    assert (tmp_path / "nested" / "sub" / "history.jsonl").exists()


def test_append_history_default_ts_is_iso(tmp_path):
    path = str(tmp_path / "history.jsonl")
    rec = ff.append_history(_sample_report(), path=path)
    # Default timestamp must be a parseable ISO-8601 string.
    from datetime import datetime

    assert datetime.fromisoformat(rec["ts"])


# --- per-window sample adequacy (Task 5: aggregate-30 is necessary-not-sufficient) ---


def _verdict_windows(_id, verdict, p_edge, dsr, pf, window_trades):
    """Verdict carrying a real windows[] array so per-window adequacy is computable."""
    n = len(window_trades)
    return {
        "_id": _id,
        "symbol": _id.split("_")[0],
        "family": "trend",
        "verdict": verdict,
        "gate_v2_metrics": {"pf_ci_lower": pf, "p_edge": p_edge, "dsr": dsr},
        "wfo_config": {"n_oos_windows": n, "total_oos_trades": sum(window_trades)},
        "windows": [{"window": i + 1, "oos_trades": t} for i, t in enumerate(window_trades)],
    }


def test_per_window_signal_computed_from_windows():
    # singlefinder-like (fat windows) vs trend-mirage (thin windows).
    v_fat = _verdict_windows("MGC_singlefinder#1", "PASS", 0.714, 1.0, 1.05,
                             [61, 56, 64, 60, 58, 63, 19])
    v_thin = _verdict_windows("MGC_trend_rank4#1", "PASS", 0.684, 1.0, 3.0,
                              [5, 5, 7, 5, 3, 4, 4, 4, 4, 3, 2, 4, 5, 3, 2, 1, 1, 3, 2])
    family, _ = ff.build_family([v_fat, v_thin])
    by = {r["id"]: r for r in family}

    fat = by["MGC_singlefinder#1"]
    assert fat["median_oos_trades_per_window"] == 60
    assert fat["n_thin_windows"] == 0
    assert fat["per_window_adequate"] is True

    thin = by["MGC_trend_rank4#1"]
    assert thin["median_oos_trades_per_window"] == 4
    assert thin["n_thin_windows"] == 14  # 14 of 19 windows below 5 trades
    assert thin["per_window_adequate"] is False
    assert 0.0 < thin["frac_trades_in_thin_windows"] <= 1.0


def test_per_window_thin_blocks_robust(monkeypatch):
    # Aggregate-adequate (67 >= 30) and BH-significant, but per-window median 4 < 5
    # -> the necessary-not-sufficient gap -> NOT robust.
    v = _verdict_windows("MGC_trend_rank4#1", "PASS", 1.0, 1.0, 3.0, [7, 5, 6, 4, 4, 3, 2])
    monkeypatch.setattr(ff, "load_verdicts", lambda *a, **k: [v])
    report = ff.run(q=0.10)
    row = report["family"][0]
    assert row["sample_adequate"] is True          # aggregate floor cleared (31 >= 30)
    assert row["per_window_adequate"] is False      # but per-window thin
    assert row["robust_edge"] is False
    assert report["n_robust_edge"] == 0


def test_per_window_adequate_allows_robust(monkeypatch):
    # Fat windows -> per-window adequate -> does not over-block a genuine edge.
    v = _verdict_windows("MGC_singlefinder#1", "PASS", 1.0, 1.0, 1.3,
                         [40, 45, 38, 42, 50, 44, 41])
    monkeypatch.setattr(ff, "load_verdicts", lambda *a, **k: [v])
    report = ff.run(q=0.10)
    row = report["family"][0]
    assert row["per_window_adequate"] is True
    assert row["robust_edge"] is True
    assert report["n_robust_edge"] == 1


def test_per_window_absent_does_not_block(monkeypatch):
    # No windows[] (legacy/aggregate-only verdict) -> per_window_adequate None ->
    # must NOT manufacture a block beyond the aggregate floor (fail-open on missing).
    v = _verdict("AAA_trend#1", "PASS", 1.0, 7, 1.0, 3.18, oos_trades=40)
    monkeypatch.setattr(ff, "load_verdicts", lambda *a, **k: [v])
    report = ff.run(q=0.10)
    row = report["family"][0]
    assert row["per_window_adequate"] is None
    assert row["robust_edge"] is True  # unchanged from the pre-Task-5 behavior
