"""Tests for options snapshot persistence helpers."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts import options_signals_snapshot as oss


def test_symbol_from_chain_url_sanitizes_cboe_path():
    assert oss._symbol_from_chain_url("https://cdn.cboe.com/api/global/delayed_quotes/options/SPY.json") == "SPY"
    assert oss._symbol_from_chain_url("https://example.test/options/qqq.json") == "QQQ"


def test_archive_raw_chain_writes_replayable_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(oss, "_CHAIN_SNAPSHOT_DIR", tmp_path / "chain_snapshots")
    now = datetime(2026, 9, 11, 10, 31, 22, tzinfo=ZoneInfo("America/Chicago"))
    raw = {"data": {"current_price": 500.25, "options": []}}

    path = oss._archive_raw_chain("SPY", raw, now)

    assert path.name == "SPY_103122.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["symbol"] == "SPY"
    assert body["source"] == "CBOE delayed quotes"
    assert body["data_delayed_minutes"] == 15
    assert body["raw"] == raw
