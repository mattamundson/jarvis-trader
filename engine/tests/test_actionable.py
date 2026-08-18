"""Tests for analytics.actionable — pure actionable-board derivation.

Covers the status-priority ladder, distance math for both directions,
R-multiple math, expiry, and honest degradation (missing price/levels never
fabricate values). Pure functions only — no I/O, no engine app.
"""

from datetime import date

from analytics.actionable import (
    ENTRY_ZONE_ATR_FRAC,
    EXPIRY_DAYS,
    derive_actionable_board,
    derive_actionable_item,
    derive_status,
)

NOW = date(2026, 7, 16)


def _row(
    *,
    symbol: str = "MES",
    action: str = "buy",
    status: str = "pending",
    entry: float | None = 5000.0,
    stop: float | None = 4980.0,
    target: float | None = 5020.0,
    atr: float | None = 10.0,
    created_at: str = "2026-07-16T10:00:00+00:00",
    confidence: float = 0.7,
) -> dict:
    return {
        "approval_id": "abc-123",
        "symbol": symbol,
        "action": action,
        "status": status,
        "quantity": 1,
        "created_at": created_at,
        "timeframe": "1h",
        "pipeline_snapshot": {
            "trade_decision": {
                "entry_price": entry,
                "stop_price": stop,
                "target_1": target,
                "atr_used": atr,
                "confidence": confidence,
            }
        },
    }


# ── derive_status priority ladder ────────────────────────────────────────────


def test_status_unknown_without_price():
    assert (
        derive_status(
            latest_close=None, entry=5000.0, stop=4980.0, target=5020.0,
            atr=10.0, long=True, age_days=0,
        )
        == "unknown"
    )


def test_status_unknown_without_entry():
    assert (
        derive_status(
            latest_close=5000.0, entry=None, stop=None, target=None,
            atr=None, long=True, age_days=0,
        )
        == "unknown"
    )


def test_status_invalidated_beats_everything_long():
    # Long: price at/below stop is invalidated even if aged out.
    assert (
        derive_status(
            latest_close=4979.0, entry=5000.0, stop=4980.0, target=5020.0,
            atr=10.0, long=True, age_days=EXPIRY_DAYS + 5,
        )
        == "invalidated"
    )


def test_status_invalidated_short():
    # Short: price at/above stop is invalidated.
    assert (
        derive_status(
            latest_close=5021.0, entry=5000.0, stop=5020.0, target=4980.0,
            atr=10.0, long=False, age_days=0,
        )
        == "invalidated"
    )


def test_status_target_reached_long():
    assert (
        derive_status(
            latest_close=5025.0, entry=5000.0, stop=4980.0, target=5020.0,
            atr=10.0, long=True, age_days=0,
        )
        == "target_reached"
    )


def test_status_expired_after_threshold():
    # Price between entry zone and stop, but too old.
    assert (
        derive_status(
            latest_close=4990.0, entry=5000.0, stop=4980.0, target=5020.0,
            atr=10.0, long=True, age_days=EXPIRY_DAYS + 1,
        )
        == "expired"
    )


def test_status_triggerable_within_entry_zone():
    # |remaining| <= ENTRY_ZONE_ATR_FRAC * atr  →  triggerable.
    close = 5000.0 - ENTRY_ZONE_ATR_FRAC * 10.0  # exactly at the band edge
    assert (
        derive_status(
            latest_close=close, entry=5000.0, stop=4980.0, target=5020.0,
            atr=10.0, long=True, age_days=0,
        )
        == "triggerable"
    )


def test_status_triggered_past_entry_toward_target():
    assert (
        derive_status(
            latest_close=5010.0, entry=5000.0, stop=4980.0, target=5020.0,
            atr=10.0, long=True, age_days=0,
        )
        == "triggered"
    )


def test_status_awaiting_entry_far_from_entry():
    assert (
        derive_status(
            latest_close=4990.0, entry=5000.0, stop=4980.0, target=5020.0,
            atr=10.0, long=True, age_days=0,
        )
        == "awaiting_entry"
    )


# ── derive_actionable_item math ──────────────────────────────────────────────


def test_item_distance_math_long():
    item = derive_actionable_item(_row(), 4990.0, 1_752_600_000.0, now=NOW)
    # Long: remaining = entry - latest = +10 (price must rise 10 pts to entry).
    assert item["distance_abs"] == 10.0
    assert item["distance_pct"] == round(10.0 / 4990.0 * 100, 4)
    assert item["distance_atr"] == 1.0
    assert item["status"] == "awaiting_entry"


def test_item_distance_math_short():
    row = _row(action="sell", entry=5000.0, stop=5020.0, target=4980.0)
    item = derive_actionable_item(row, 5010.0, None, now=NOW)
    # Short: remaining = (entry - latest) * -1 = +10 (price must fall to entry).
    assert item["direction"] == "short"
    assert item["distance_abs"] == 10.0
    assert item["distance_atr"] == 1.0


def test_item_r_multiple_math():
    # risk = |5000 - 4980| = 20; target 5020 → planned RR = 1.0.
    # latest 5010 → current R = (5010-5000)/20 = +0.5.
    item = derive_actionable_item(_row(), 5010.0, None, now=NOW)
    assert item["planned_rr"] == 1.0
    assert item["current_r"] == 0.5


def test_item_notional_uses_contract_multiplier():
    # MES multiplier is $5/pt.
    item = derive_actionable_item(_row(), 5000.0, None, now=NOW)
    assert item["notional_per_contract"] == 25000.0


def test_item_missing_levels_degrade_to_null():
    row = _row(entry=None, stop=None, target=None, atr=None)
    # Row-level entry_price fallback is also absent.
    row["entry_price"] = None
    item = derive_actionable_item(row, 5000.0, None, now=NOW)
    assert item["status"] == "unknown"
    assert item["distance_abs"] is None
    assert item["planned_rr"] is None
    assert item["current_r"] is None


def test_item_zero_sentinel_target_not_target_reached():
    # 0.0 levels are missing-value sentinels — a long with target_1=0.0 must
    # not read as target_reached against any positive price.
    row = _row(target=0.0)
    item = derive_actionable_item(row, 4990.0, None, now=NOW)
    assert item["target_1"] is None
    assert item["status"] == "awaiting_entry"
    assert item["planned_rr"] is None


def test_item_missing_price_is_unknown_not_fabricated():
    item = derive_actionable_item(_row(), None, None, now=NOW)
    assert item["status"] == "unknown"
    assert item["latest_price"] is None
    assert item["distance_pct"] is None
    assert item["notional_per_contract"] is None


# ── derive_actionable_board ──────────────────────────────────────────────────


# Fixed clock for board tests: prices stamped 60s before "now" are fresh.
NOW_TS = 1_752_600_060.0
PRICE_AS_OF = 1_752_600_000.0


def _prices(**by_symbol: float) -> dict:
    return {
        sym: {"last_price": px, "as_of": PRICE_AS_OF, "is_live": True, "source": "ibkr"}
        for sym, px in by_symbol.items()
    }


def test_board_filters_holds_and_rejected():
    rows = [
        _row(symbol="MES"),
        {**_row(symbol="MGC"), "action": "hold"},
        _row(symbol="MNQ", status="rejected"),
    ]
    board = derive_actionable_board(rows, _prices(MES=4990.0), now=NOW, now_ts=NOW_TS)
    assert board["available"] is True
    assert [it["symbol"] for it in board["items"]] == ["MES"]


def test_board_dedupes_to_newest_per_symbol_side():
    # Rows arrive newest-first; the second MES buy must be dropped.
    newer = _row(created_at="2026-07-16T10:00:00+00:00", entry=5002.0)
    older = _row(created_at="2026-07-15T10:00:00+00:00", entry=4900.0)
    board = derive_actionable_board([newer, older], _prices(MES=5000.0), now=NOW, now_ts=NOW_TS)
    assert board["count"] == 1
    assert board["items"][0]["entry_price"] == 5002.0


def test_board_sorts_actionable_first():
    triggerable = _row(symbol="MES", entry=5000.0)     # price at entry band
    awaiting = _row(symbol="MGC", entry=3000.0, stop=2990.0, target=3010.0, atr=5.0)
    board = derive_actionable_board(
        [awaiting, triggerable], _prices(MES=5000.0, MGC=2996.0), now=NOW, now_ts=NOW_TS
    )
    assert [it["status"] for it in board["items"]] == ["triggerable", "awaiting_entry"]


def test_board_no_price_snapshot_degrades_honestly():
    board = derive_actionable_board([_row()], {}, now=NOW, now_ts=NOW_TS)
    assert board["count"] == 1
    assert board["items"][0]["status"] == "unknown"


def test_board_cached_source_withheld_even_with_fresh_timestamp():
    # THE trap: /prices/snapshot stamps as_of at FETCH time, so a csv_cache
    # close from yesterday can carry a fresh timestamp. Tier membership must
    # withhold the status regardless — price stays visible + flagged.
    cached = {
        "MES": {"last_price": 5000.0, "as_of": NOW_TS - 5.0, "is_live": False, "source": "csv_cache"}
    }
    board = derive_actionable_board([_row(entry=5000.0)], cached, now=NOW, now_ts=NOW_TS)
    item = board["items"][0]
    assert item["status"] == "unknown"
    assert item["price_stale"] is True
    assert item["latest_price"] == 5000.0
    assert item["distance_pct"] is None
    assert item["current_r"] is None


def test_board_old_timestamp_on_live_source_is_stale():
    # A live-tier price served from the 60s snapshot cache long ago is stale.
    old = {
        "MES": {"last_price": 5000.0, "as_of": NOW_TS - 7200.0, "is_live": True, "source": "ibkr"}
    }
    board = derive_actionable_board([_row(entry=5000.0)], old, now=NOW, now_ts=NOW_TS)
    assert board["items"][0]["status"] == "unknown"
    assert board["items"][0]["price_stale"] is True


def test_board_fresh_delayed_price_still_derives_status():
    # Fresh delayed REST read (polygon) is usable — flagged, not withheld.
    delayed = {
        "MES": {"last_price": 5000.0, "as_of": NOW_TS - 60.0, "is_live": False, "source": "polygon"}
    }
    board = derive_actionable_board([_row(entry=5000.0)], delayed, now=NOW, now_ts=NOW_TS)
    item = board["items"][0]
    assert item["status"] == "triggerable"
    assert item["price_stale"] is False
    assert item["price_is_live"] is False


def test_board_missing_as_of_or_source_counts_as_stale():
    no_stamp = {"MES": {"last_price": 5000.0, "is_live": True, "source": "ibkr"}}
    board = derive_actionable_board([_row(entry=5000.0)], no_stamp, now=NOW, now_ts=NOW_TS)
    assert board["items"][0]["status"] == "unknown"
    assert board["items"][0]["price_stale"] is True

    no_source = {"MES": {"last_price": 5000.0, "as_of": NOW_TS - 5.0, "is_live": True}}
    board = derive_actionable_board([_row(entry=5000.0)], no_source, now=NOW, now_ts=NOW_TS)
    assert board["items"][0]["status"] == "unknown"
    assert board["items"][0]["price_stale"] is True
