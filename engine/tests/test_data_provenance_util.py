"""Tests for the shared data-provenance helper (utils/data_provenance.py).

Extracted from main.py's `_build_data_provenance` / `_log_decision` (PR #286)
so the secondary `insert_decision` callers (pipeline_router, decisions_router,
signal_scanner) can stamp the same {last_bar_source, serve_age_s} fields.
Pure-helper behavior pinned here mirrors tests/test_decision_provenance.py.
"""

from __future__ import annotations

from utils.data_provenance import build_data_provenance, stamp_signal_data


class _FakeDM:
    """Stand-in exposing the two provenance surfaces `build_data_provenance` reads."""

    def __init__(self, source, freshness):
        self._last_bar_source = source
        self._freshness = freshness

    def symbol_freshness(self):
        return self._freshness


def test_build_data_provenance_captures_source_and_per_symbol_age():
    dm = _FakeDM("csv_cache", {"MES": 4210.5})
    prov = build_data_provenance(dm, "mes")  # symbol upper-cased internally
    assert prov == {"last_bar_source": "csv_cache", "serve_age_s": 4210.5}


def test_build_data_provenance_serve_age_none_when_symbol_unseen():
    dm = _FakeDM("ibkr", {"MGC": 3.0})
    prov = build_data_provenance(dm, "MES")
    assert prov["last_bar_source"] == "ibkr"
    assert prov["serve_age_s"] is None


def test_build_data_provenance_none_when_no_data_manager():
    assert build_data_provenance(None, "MES") is None


def test_build_data_provenance_defensive_on_broken_freshness():
    class Boom:
        _last_bar_source = "ibkr"

        def symbol_freshness(self):
            raise RuntimeError("boom")

    prov = build_data_provenance(Boom(), "MES")
    assert prov == {"last_bar_source": "ibkr", "serve_age_s": None}


def test_stamp_signal_data_merges_without_mutating_caller_dict():
    caller_signal = {"rsi": 55}
    prov = {"last_bar_source": "sqlite_cache", "serve_age_s": 12.0}

    stamped = stamp_signal_data(caller_signal, prov)

    assert stamped == {"rsi": 55, "data_provenance": prov}
    assert "data_provenance" not in caller_signal  # copy, not in-place


def test_stamp_signal_data_noop_when_provenance_none():
    caller_signal = {"rsi": 55}
    assert stamp_signal_data(caller_signal, None) is caller_signal


def test_stamp_signal_data_noop_when_signal_data_not_dict():
    prov = {"last_bar_source": "ibkr", "serve_age_s": 1.0}
    assert stamp_signal_data(None, prov) is None
