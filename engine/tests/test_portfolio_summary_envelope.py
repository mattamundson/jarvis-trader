"""Tests for /portfolio/summary's provenance envelope fields (P4-1).

P4-1 wires the existing data-provenance envelope (engine/data/provenance.py,
Phase 1) into /portfolio/summary's price-derived aggregates: unrealized_pnl,
total_pnl, and total_daily_pnl each get an additive ``*_envelope`` field
carrying {value, source, as_of, is_live, stale_after_s}, built by aggregating
the per-position provenance already computed by ``_compute_unrealized``
(itself already Phase-1-wired for ``/paper/positions/unrealized``).

realized_pnl comes from the closed-trade ledger, not the live price feed, so
its envelope is always is_live=True -- exercising the proof line's "trade
counts stay live" half while the price-derived envelopes flip False the
moment the feed stops.

Pure unit tests against the two aggregation helpers directly (no FastAPI
TestClient, no orchestrator/paper_tracker mocking) -- mirrors the existing
``_compute_unrealized``-level testing convention in
test_portfolio_unrealized_guard.py.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from routers.portfolio_router import _build_price_envelope, _ledger_envelope  # noqa: E402


def test_no_open_positions_is_trivially_live():
    env = _build_price_envelope(0.0, [])
    assert env["value"] == 0.0
    assert env["source"] == "ledger"
    assert env["is_live"] is True


def test_all_positions_live_feed_up():
    # Two positions, both marked from a live-tier, connected, fresh source.
    now = time.time()
    marks = [(True, "ibkr", now), (True, "ibkr", now - 1)]
    env = _build_price_envelope(1234.5, marks)
    assert env["value"] == 1234.5
    assert env["source"] == "ibkr"
    assert env["is_live"] is True


def test_stopping_the_feed_flips_price_derived_field_to_not_live():
    # One position live, one falls back to a stale/disconnected mark once the
    # feed stops (e.g. csv_cache fallback) -> the AGGREGATE must flip False,
    # matching the fail-safe "one bad mark taints the whole aggregate" rule
    # already used for unrealized_marks_stale.
    now = time.time()
    marks = [(True, "ibkr", now), (False, "csv_cache", now - 9000)]
    env = _build_price_envelope(-42.0, marks)
    assert env["is_live"] is False


def test_full_feed_outage_all_positions_not_live():
    now = time.time()
    marks = [(False, "csv_cache", now - 9000), (False, "unavailable", None)]
    env = _build_price_envelope(0.0, marks)
    assert env["is_live"] is False
    assert env["source"] == "mixed"


def test_single_shared_source_is_reported_directly():
    now = time.time()
    marks = [(True, "ibkr", now), (True, "ibkr", now)]
    env = _build_price_envelope(10.0, marks)
    assert env["source"] == "ibkr"


def test_as_of_is_the_oldest_contributing_mark():
    # Conservative aggregation: report the staleness of the LEAST fresh mark.
    now = time.time()
    marks = [(True, "ibkr", now), (True, "ibkr", now - 30)]
    env = _build_price_envelope(5.0, marks)
    assert env["as_of"] == now - 30


def test_ledger_envelope_is_always_live_trade_counts_stay_live():
    # realized_pnl is a booked ledger fact, not a live-feed read -- it never
    # goes stale, even while the price-derived envelopes above flip False.
    env = _ledger_envelope(500.0)
    assert env["value"] == 500.0
    assert env["source"] == "ledger"
    assert env["is_live"] is True


def test_envelope_shape_matches_data_envelope_contract():
    env = _build_price_envelope(1.0, [(True, "ibkr", time.time())])
    assert set(env.keys()) == {"value", "source", "as_of", "is_live", "stale_after_s"}
