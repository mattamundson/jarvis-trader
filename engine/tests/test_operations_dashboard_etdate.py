"""Regression: dashboard 'today' filter must bucket UTC trade stamps by ET date.

Trade timestamps are written in UTC (utcnow()+"Z"). The daily P&L card filtered
them against an ET date with a raw string startswith(), so an evening ET trade —
21:00 ET = 01:00 UTC the NEXT calendar day — failed the match and silently
vanished from the dashboard's daily P&L. These tests pin the conversion.
"""

from __future__ import annotations

import json
from datetime import date

from api import operations_dashboard as od


class TestTradeOnEtDate:
    def test_evening_et_trade_stamped_next_utc_day_is_included(self):
        # 21:00 ET on 2026-06-05 is 01:00 UTC on 2026-06-06 (EDT, UTC-4).
        ts = "2026-06-06T01:00:00Z"
        assert od._trade_on_et_date(ts, date(2026, 6, 5)) is True  # ET day, not UTC day
        assert od._trade_on_et_date(ts, date(2026, 6, 6)) is False  # not the UTC day

    def test_morning_trade_same_utc_and_et_day(self):
        # 10:00 ET = 14:00 UTC, same calendar date.
        assert od._trade_on_et_date("2026-06-05T14:00:00Z", date(2026, 6, 5)) is True

    def test_other_day_excluded(self):
        assert od._trade_on_et_date("2026-06-04T14:00:00Z", date(2026, 6, 5)) is False

    def test_none_timestamp_is_false(self):
        assert od._trade_on_et_date(None, date(2026, 6, 5)) is False

    def test_malformed_timestamp_falls_back_to_prefix(self):
        # Unparseable → last-resort prefix match against the ET date.
        assert od._trade_on_et_date("2026-06-05 garbage", date(2026, 6, 5)) is True
        assert od._trade_on_et_date("not-a-date", date(2026, 6, 5)) is False


class TestLoadPaperTradesToday:
    def test_evening_trade_not_dropped_from_today(self, tmp_path, monkeypatch):
        f = tmp_path / "paper_trades.json"
        f.write_text(
            json.dumps(
                [
                    {"timestamp": "2026-06-05T14:00:00Z", "symbol": "MES"},  # 10:00 ET
                    {"timestamp": "2026-06-06T01:00:00Z", "symbol": "MES"},  # 21:00 ET same ET day
                    {"timestamp": "2026-06-06T18:00:00Z", "symbol": "MES"},  # next ET day
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(od, "_PAPER_TRADES_JSON", f)

        today = od._load_paper_trades_today(target_date=date(2026, 6, 5))

        # Both the morning AND the evening (next-UTC-day) trade belong to ET 06-05.
        assert len(today) == 2
        stamps = {t["timestamp"] for t in today}
        assert "2026-06-06T01:00:00Z" in stamps  # the previously-dropped evening trade
        assert "2026-06-06T18:00:00Z" not in stamps  # genuinely the next ET day
