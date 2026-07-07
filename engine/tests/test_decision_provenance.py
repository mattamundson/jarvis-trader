"""Tests for decision data-provenance stamping (Move 4 — data-truth, safe half).

`_log_decision` now records WHAT DATA each decision was based on — the data tier
(`last_bar_source`) and the per-symbol serve-age — so a post-hoc audit can tell a
live-IBKR decision from one made on a stale CSV-cache fallback (the 2026-06-29
frozen-MES-5300 class). This is purely additive: it never changes a trade
decision and must never raise into the decision path.
"""

from __future__ import annotations

import main


class _FakeDM:
    """Stand-in exposing the two provenance surfaces `_build_data_provenance` reads."""

    def __init__(self, source, freshness):
        self._last_bar_source = source
        self._freshness = freshness

    def symbol_freshness(self):
        return self._freshness


# --- pure helper --------------------------------------------------------------


def test_provenance_captures_source_and_per_symbol_age():
    dm = _FakeDM("csv_cache", {"MES": 4210.5})
    prov = main._build_data_provenance(dm, "mes")  # symbol upper-cased internally
    assert prov == {"last_bar_source": "csv_cache", "serve_age_s": 4210.5}


def test_provenance_serve_age_none_when_symbol_unseen():
    dm = _FakeDM("ibkr", {"MGC": 3.0})
    prov = main._build_data_provenance(dm, "MES")
    assert prov["last_bar_source"] == "ibkr"
    assert prov["serve_age_s"] is None


def test_provenance_none_when_no_data_manager():
    assert main._build_data_provenance(None, "MES") is None


def test_provenance_defensive_on_broken_freshness():
    class Boom:
        _last_bar_source = "ibkr"

        def symbol_freshness(self):
            raise RuntimeError("boom")

    prov = main._build_data_provenance(Boom(), "MES")
    # source still captured; a broken freshness call degrades to None, never raises
    assert prov == {"last_bar_source": "ibkr", "serve_age_s": None}


# --- _log_decision wiring -----------------------------------------------------


def test_log_decision_stamps_persisted_signal_data(monkeypatch):
    captured: dict = {}

    class _FakeDB:
        def insert_decision(self, **kwargs):
            captured.update(kwargs)
            return 1

    dm = _FakeDM("sqlite_cache", {"MES": 12.0})
    monkeypatch.setattr(main, "data_manager", dm)
    monkeypatch.setattr(main, "db_manager", _FakeDB())
    monkeypatch.setattr(main, "_decision_log", [])

    caller_signal = {"rsi": 55}
    main._log_decision("MES", "buy", confidence=0.8, signal_data=caller_signal)

    sig = captured["signal_data"]
    assert sig["data_provenance"] == {"last_bar_source": "sqlite_cache", "serve_age_s": 12.0}
    assert sig["rsi"] == 55  # caller's fields preserved
    # caller's dict must NOT be mutated (copy-merge, not in-place)
    assert "data_provenance" not in caller_signal
    # ring-buffer entry is stamped too (for the dashboard feed)
    assert main._decision_log[-1]["data_provenance"]["last_bar_source"] == "sqlite_cache"


def test_log_decision_survives_when_data_manager_absent(monkeypatch):
    captured: dict = {}

    class _FakeDB:
        def insert_decision(self, **kwargs):
            captured.update(kwargs)
            return 1

    monkeypatch.setattr(main, "data_manager", None)
    monkeypatch.setattr(main, "db_manager", _FakeDB())
    monkeypatch.setattr(main, "_decision_log", [])

    main._log_decision("MES", "hold", source="scanner")
    # provenance None -> default signal_data used, no crash, entry still recorded
    assert captured["signal_data"] == {"source": "scanner", "summary": ""}
    assert main._decision_log[-1]["data_provenance"] is None
