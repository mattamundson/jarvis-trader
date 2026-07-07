"""Unit tests for the multi-pair relative-value scan (backtest/spread_pairs_scan.py).

Covers the new logic only (the spread math is tested in test_spread_backtest.py):
  - classify_verdict: the CANDIDATE / NON-STATIONARY / NO_EDGE decision, incl. the
    ES-NQ-style "pooled PASS but one-sided" trap -> NON-STATIONARY (not CANDIDATE)
  - load_pair: inner-join alignment on timestamp via tmp CSVs

Read-only analysis; not on the trading path.
"""

from __future__ import annotations

from backtest import spread_pairs_scan as ps

# --- classify_verdict ------------------------------------------------------


def test_candidate_requires_pass_and_both_halves_positive():
    pooled, stat, v = ps.classify_verdict(1.5, 1.0, 200, h1_sum=0.4, h2_sum=0.6)
    assert pooled and stat and v == "CANDIDATE"


def test_pooled_pass_but_back_loaded_is_non_stationary():
    # the ES-NQ trap: pooled thresholds clear, but H1 loses -> NOT a candidate
    pooled, stat, v = ps.classify_verdict(2.45, 1.0, 256, h1_sum=-0.02, h2_sum=0.9)
    assert pooled and not stat and v == "NON-STATIONARY"


def test_both_positive_but_magnitude_imbalanced_is_back_loaded():
    # MES-M2K shape: both halves profitable, but H1 carries only ~7% of profit.
    # Passes the binary stationarity check yet is a recent-regime edge -> BACK-LOADED,
    # a rung below CANDIDATE. stationary stays True (both halves > 0).
    pooled, stat, v = ps.classify_verdict(2.26, 1.0, 264, h1_sum=0.087, h2_sum=1.213)
    assert pooled and stat and v == "BACK-LOADED"


def test_balanced_halves_earn_candidate():
    # H1 share = 0.4 / 1.0 = 40% >= 20% floor -> CANDIDATE
    pooled, stat, v = ps.classify_verdict(1.5, 1.0, 200, h1_sum=0.4, h2_sum=0.6)
    assert pooled and stat and v == "CANDIDATE"


def test_magnitude_balance_boundary_inclusive():
    # exactly 20% profit-share in the weaker half -> CANDIDATE (inclusive)
    assert ps.classify_verdict(1.5, 1.0, 200, h1_sum=0.20, h2_sum=0.80)[2] == "CANDIDATE"
    # a hair under 20% -> BACK-LOADED
    assert ps.classify_verdict(1.5, 1.0, 200, h1_sum=0.199, h2_sum=0.801)[2] == "BACK-LOADED"


def test_fails_pooled_thresholds_is_no_edge():
    assert ps.classify_verdict(0.9, 0.6, 200, 0.1, 0.1)[2] == "NO_EDGE"  # pf_ci low
    assert ps.classify_verdict(1.5, 0.5, 200, 0.1, 0.1)[2] == "NO_EDGE"  # p_edge low
    assert ps.classify_verdict(1.5, 1.0, 10, 0.1, 0.1)[2] == "NO_EDGE"  # too few trades


def test_missing_halves_cannot_be_candidate():
    pooled, stat, v = ps.classify_verdict(1.5, 1.0, 200, None, None)
    assert pooled and not stat and v == "NON-STATIONARY"


def test_threshold_boundaries_inclusive():
    # exactly at the gate-v2 floors -> pass
    assert ps.classify_verdict(1.10, 0.95, 30, 0.1, 0.1)[0] is True
    assert ps.classify_verdict(1.099, 0.95, 30, 0.1, 0.1)[0] is False


# --- load_pair -------------------------------------------------------------


def test_load_pair_inner_joins_on_timestamp(tmp_path):
    # Files must match the _find_latest_cache contract <ROOT>_<START>_<END>_<tf>.csv;
    # load_pair resolves each leg to its latest cache by end-date rather than a pinned
    # filename, so the test writes contract-conforming names and passes bare roots.
    (tmp_path / "A_2026-01-01_2026-01-01_1h.csv").write_text(
        "timestamp,close\n2026-01-01T00:00:00,10\n2026-01-01T01:00:00,11\n2026-01-01T02:00:00,12\n",
        encoding="utf-8",
    )
    # B is missing the 01:00 bar -> inner join drops it
    (tmp_path / "B_2026-01-01_2026-01-01_1h.csv").write_text(
        "timestamp,close\n2026-01-01T00:00:00,20\n2026-01-01T02:00:00,22\n2026-01-01T03:00:00,23\n",
        encoding="utf-8",
    )
    ts, a, b = ps.load_pair("A", "B", "1h", cache_dir=tmp_path)
    assert len(ts) == 2  # only 00:00 and 02:00 overlap
    assert list(a) == [10.0, 12.0]
    assert list(b) == [20.0, 22.0]


def test_load_pair_picks_latest_end_date_not_lexicographic(tmp_path):
    # Regression for the loader-staleness bug class: when two caches exist for a
    # leg, load_pair must pick the one with the newest END date, not the
    # lexicographically-last filename. The stale file has the lex-greater name
    # (start 2026-02) but an OLDER end date -- the fresh file (end 2026-12) wins.
    (tmp_path / "A_2026-02-01_2026-03-01_1h.csv").write_text(
        "timestamp,close\n2026-01-01T00:00:00,999\n", encoding="utf-8"  # stale -> must be ignored
    )
    (tmp_path / "A_2026-01-01_2026-12-01_1h.csv").write_text(
        "timestamp,close\n2026-01-01T00:00:00,10\n", encoding="utf-8"  # fresh -> must win
    )
    (tmp_path / "B_2026-01-01_2026-12-01_1h.csv").write_text(
        "timestamp,close\n2026-01-01T00:00:00,20\n", encoding="utf-8"
    )
    _, a, _ = ps.load_pair("A", "B", "1h", cache_dir=tmp_path)
    assert list(a) == [10.0]  # fresh cache, not the stale 999
