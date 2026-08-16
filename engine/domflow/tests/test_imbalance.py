"""Pure unit tests for the DOM imbalance signal — no I/O, no IBKR mock.

Per the Phase-1 spec: the only verification promised up front is
type-checks + unit-tested pure function. Live-depth → imbalance → SQLite →
dashboard is verified separately end-to-end against the real paper gateway
(not mocked here).

Runs with: python -m pytest engine/domflow/tests/test_imbalance.py
"""

from __future__ import annotations

from collections import namedtuple

from engine.domflow.imbalance import (
    compute_imbalance,
    imbalance_label,
    snapshot_payload,
)

# Duck-typed stand-in for ib_async's DOMLevel (price, size, marketMaker).
Level = namedtuple("Level", ["price", "size", "marketMaker"])


def _bids(prices_sizes):
    return [Level(p, s, "") for p, s in prices_sizes]


def _asks(prices_sizes):
    return [Level(p, s, "") for p, s in prices_sizes]


# ── compute_imbalance ────────────────────────────────────────────────────────

def test_all_bid_book_imbalance_is_one():
    bids = _bids([(100.0, 50), (99.5, 40), (99.0, 30), (98.5, 20), (98.0, 10)])
    asks = _bids([])  # empty ask side
    assert compute_imbalance(bids, asks) == 1.0


def test_all_ask_book_imbalance_is_zero():
    bids = _bids([])
    asks = _bids([(100.5, 50), (101.0, 40), (101.5, 30), (102.0, 20), (102.5, 10)])
    assert compute_imbalance(bids, asks) == 0.0


def test_balanced_book_is_half():
    bids = _bids([(100.0, 50), (99.5, 50), (99.0, 50), (98.5, 50), (98.0, 50)])
    asks = _bids([(100.5, 50), (101.0, 50), (101.5, 50), (102.0, 50), (102.5, 50)])
    assert compute_imbalance(bids, asks) == 0.5


def test_empty_book_handled_without_div_zero():
    assert compute_imbalance([], []) == 0.0


def test_top_n_limits_the_sum():
    # Top-1 imbalance differs from top-5 imbalance.
    bids = _bids([(100.0, 10), (99.5, 1000), (99.0, 1000), (98.5, 1000), (98.0, 1000)])
    asks = _bids([(100.5, 10), (101.0, 10), (101.5, 10), (102.0, 10), (102.5, 10)])
    top1 = compute_imbalance(bids, asks, top_n=1)
    top5 = compute_imbalance(bids, asks, top_n=5)
    assert top1 == 0.5
    assert top5 > 0.95  # deep bid pressure dominates at 5 levels


def test_imbalance_heavy_bid_side():
    bids = _bids([(100.0, 90), (99.5, 80), (99.0, 70), (98.5, 60), (98.0, 50)])
    asks = _bids([(100.5, 10), (101.0, 10), (101.5, 10), (102.0, 10), (102.5, 10)])
    ratio = compute_imbalance(bids, asks)
    assert 0.6 < ratio < 1.0


def test_imbalance_heavy_ask_side():
    bids = _bids([(100.0, 10), (99.5, 10), (99.0, 10), (98.5, 10), (98.0, 10)])
    asks = _bids([(100.5, 90), (101.0, 80), (101.5, 70), (102.0, 60), (102.5, 50)])
    ratio = compute_imbalance(bids, asks)
    assert 0.0 < ratio < 0.4


def test_malformed_level_size_is_skipped():
    class BadLevel:
        price = 100.0

    class StrLevel:
        price = 100.0
        size = "25"  # string size — coercible

    class NegLevel:
        price = 100.0
        size = -5  # non-positive — must not inflate volume

    bids = [BadLevel(), StrLevel(), NegLevel(), Level(99.0, 10, "")]
    asks = _bids([(100.5, 10), (101.0, 10), (101.5, 10), (102.0, 10), (102.5, 10)])
    # Only StrLevel (25) + Level (10) contribute: 35 / (35 + 50) = 0.4118
    ratio = compute_imbalance(bids, asks)
    assert abs(ratio - 35.0 / 85.0) < 1e-9


# ── imbalance_label ──────────────────────────────────────────────────────────

def test_label_bull_above_threshold():
    assert imbalance_label(0.61) == "bull"


def test_label_bear_below_threshold():
    assert imbalance_label(0.39) == "bear"


def test_label_neutral_between_thresholds():
    assert imbalance_label(0.5) == "neutral"


def test_label_exact_threshold_is_neutral():
    # Spec: bull when > 0.6, bear when < 0.4 — the boundaries are neutral.
    assert imbalance_label(0.6) == "neutral"
    assert imbalance_label(0.4) == "neutral"


# ── snapshot_payload ─────────────────────────────────────────────────────────

def test_snapshot_payload_contract():
    bids = _bids([(100.0, 90), (99.5, 80), (99.0, 70), (98.5, 60), (98.0, 50)])
    asks = _bids([(100.5, 10), (101.0, 10), (101.5, 10), (102.0, 10), (102.5, 10)])
    payload = snapshot_payload("MES", bids, asks, extra={"stale": False, "age_seconds": 0})
    assert payload["symbol"] == "MES"
    assert 0.6 < payload["imbalance_ratio"] < 1.0
    assert payload["label"] == "bull"
    assert payload["stale"] is False
    assert payload["age_seconds"] == 0
