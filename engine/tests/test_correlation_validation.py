"""P2.3 validation: pure helpers for the concurrent-exposure analysis.

The analysis replays the real paper-trade history to find windows where >=2
positions were open at once, then measures how each correlation-sizing approach
(binary threshold vs continuous portfolio-variance) would have trimmed the
newer position. These two pure helpers are the load-bearing correctness:

  risk_at_stop          dollar risk of a position to its stop
  find_concurrent_pairs overlap detection (which positions were open together)
"""

from risk.correlation_validation import (
    aligned_returns_from_ts_closes,
    find_concurrent_pairs,
    risk_at_stop,
)


def test_risk_at_stop_basic():
    # MES: 2 lots, 10 points to stop, $5/point => 2 * 10 * 5 = 100
    assert risk_at_stop(entry_price=5000.0, stop_loss=4990.0, quantity=2, multiplier=5.0) == 100.0


def test_risk_at_stop_is_absolute_for_shorts():
    # Short: stop above entry; risk is still positive.
    assert risk_at_stop(entry_price=4990.0, stop_loss=5000.0, quantity=1, multiplier=5.0) == 50.0


def test_risk_at_stop_missing_stop_returns_zero():
    assert risk_at_stop(entry_price=5000.0, stop_loss=None, quantity=1, multiplier=5.0) == 0.0
    assert risk_at_stop(entry_price=5000.0, stop_loss=0.0, quantity=1, multiplier=5.0) == 0.0


def test_no_overlap_yields_no_pairs():
    # B starts after A ends.
    intervals = [(0.0, 1.0, "MES", "a"), (2.0, 3.0, "MGC", "b")]
    assert find_concurrent_pairs(intervals) == []


def test_overlapping_pair_detected_with_newer_first():
    # A: [0,5], B: [2,4] => overlap [2,4]; B is the newer (later start).
    intervals = [(0.0, 5.0, "MES", "a"), (2.0, 4.0, "MGC", "b")]
    pairs = find_concurrent_pairs(intervals)
    assert len(pairs) == 1
    newer, older, ostart, oend = pairs[0]
    assert newer[2] == "MGC" and older[2] == "MES"
    assert ostart == 2.0 and oend == 4.0


def test_touching_intervals_do_not_overlap():
    # B starts exactly when A ends => not concurrent.
    intervals = [(0.0, 2.0, "MES", "a"), (2.0, 4.0, "MGC", "b")]
    assert find_concurrent_pairs(intervals) == []


def test_unsorted_input_is_handled():
    intervals = [(2.0, 4.0, "MGC", "b"), (0.0, 5.0, "MES", "a")]
    pairs = find_concurrent_pairs(intervals)
    assert len(pairs) == 1
    newer, older, _, _ = pairs[0]
    assert newer[2] == "MGC" and older[2] == "MES"


def test_three_way_overlap_yields_three_pairs():
    intervals = [
        (0.0, 9.0, "MES", "a"),
        (1.0, 8.0, "MGC", "b"),
        (2.0, 7.0, "MNQ", "c"),
    ]
    pairs = find_concurrent_pairs(intervals)
    assert len(pairs) == 3  # a-b, a-c, b-c


# --------------------------------------------------------------------------- #
# aligned_returns_from_ts_closes — timestamp-align before computing returns
# --------------------------------------------------------------------------- #
def test_alignment_intersects_timestamps():
    # MGC has an extra leading bar; only the shared timestamps are used.
    ts_closes = {
        "MES": [("t1", 100.0), ("t2", 101.0), ("t3", 102.0)],
        "MGC": [("t0", 50.0), ("t1", 200.0), ("t2", 202.0), ("t3", 204.0)],
    }
    rets = aligned_returns_from_ts_closes(ts_closes)
    # Common ts = t1,t2,t3 => 2 returns each.
    assert len(rets["MES"]) == 2
    assert len(rets["MGC"]) == 2


def test_alignment_preserves_return_correspondence():
    # On the shared grid both move proportionally => returns line up 1:1.
    ts_closes = {
        "MES": [("t1", 100.0), ("t2", 110.0), ("t3", 121.0)],
        "MGC": [("t1", 200.0), ("t2", 220.0), ("t3", 242.0)],
    }
    rets = aligned_returns_from_ts_closes(ts_closes)
    assert rets["MES"] == rets["MGC"]  # both +10% then +10%


def test_alignment_sorts_by_timestamp():
    # Unsorted input must still align chronologically.
    ts_closes = {
        "MES": [("t3", 102.0), ("t1", 100.0), ("t2", 101.0)],
        "MGC": [("t2", 201.0), ("t3", 202.0), ("t1", 200.0)],
    }
    rets = aligned_returns_from_ts_closes(ts_closes)
    assert len(rets["MES"]) == 2 and len(rets["MGC"]) == 2


def test_alignment_empty_intersection_yields_empty():
    ts_closes = {
        "MES": [("t1", 100.0), ("t2", 101.0)],
        "MGC": [("t8", 200.0), ("t9", 201.0)],
    }
    rets = aligned_returns_from_ts_closes(ts_closes)
    assert rets["MES"] == [] and rets["MGC"] == []
