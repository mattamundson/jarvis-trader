"""
Unit tests for engine/analytics/scenario.py

Tests compute_entry_timing_scenarios() on synthetic bars_df for both LONG
and SHORT trades, verifying:
  - offset=0 reproduces actual PnL exactly
  - a known earlier-entry delta is correct
  - empty/invalid inputs return []
"""

from __future__ import annotations

import pandas as pd
import pytest

from analytics.scenario import compute_entry_timing_scenarios

# ── Synthetic bar fixtures ────────────────────────────────────────────────────
#
# 7 bars, chronologically ordered (index 0 = oldest).
# "open" prices: [98, 99, 100, 101, 102, 103, 104]
# Entry bar index = 3 (open=101, which is NOT our actual entry price — we
# pass actual_entry_price=100.0 to test that offset=0 uses the actual price).
#
# LONG exits at 105.0, multiplier=5.0, qty=2:
#   offset=0: pnl = (105 - 100) * 5 * 2 = 50.0   (uses actual_entry_price)
#   offset=-1 (bar 2, open=100): pnl = (105-100)*5*2 = 50.0, delta=0.0
#   offset=-2 (bar 1, open=99): pnl = (105-99)*5*2 = 60.0, delta=+10.0
#   offset=-3 (bar 0, open=98): pnl = (105-98)*5*2 = 70.0, delta=+20.0
#   offset=+1 (bar 4, open=102): pnl = (105-102)*5*2 = 30.0, delta=-20.0
#
# SHORT exits at 95.0, multiplier=5.0, qty=2:
#   offset=0: pnl = (100-95)*5*2 = 50.0
#   offset=-2 (bar 1, open=99): pnl = (99-95)*5*2 = 40.0, delta=-10.0
#   offset=+1 (bar 4, open=102): pnl = (102-95)*5*2 = 70.0, delta=+20.0

_BARS = pd.DataFrame(
    {
        "open":  [98.0, 99.0, 100.0, 101.0, 102.0, 103.0, 104.0],
        "high":  [99.0, 100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        "low":   [97.0, 98.0,  99.0, 100.0, 101.0, 102.0, 103.0],
        "close": [98.5, 99.5, 100.5, 101.5, 102.5, 103.5, 104.5],
    }
)

_ACTUAL_ENTRY = 100.0
_EXIT_LONG = 105.0
_EXIT_SHORT = 95.0
_ENTRY_BAR_IDX = 3
_MULTIPLIER = 5.0
_QTY = 2.0
_OFFSETS = [-3, -2, -1, 0, 1, 2, 3]


# ── Helper ───────────────────────────────────────────────────────────────────


def _get_row(results: list[dict], offset: int) -> dict:
    for r in results:
        if r["offset_bars"] == offset:
            return r
    raise KeyError(f"offset={offset} not found in results")


# ── LONG tests ────────────────────────────────────────────────────────────────


class TestLong:
    """LONG trade: entry=100, exit=105, multiplier=5, qty=2."""

    def setup_method(self):
        self.results = compute_entry_timing_scenarios(
            side="buy",
            actual_entry_price=_ACTUAL_ENTRY,
            exit_price=_EXIT_LONG,
            bars_df=_BARS,
            entry_bar_index=_ENTRY_BAR_IDX,
            offsets=_OFFSETS,
            multiplier=_MULTIPLIER,
            qty=_QTY,
        )

    def test_returns_one_row_per_offset(self):
        assert len(self.results) == len(_OFFSETS)

    def test_offset_zero_reproduces_actual_pnl(self):
        row = _get_row(self.results, 0)
        # pnl = (105 - 100) * 5 * 2 = 50.0
        assert row["pnl_usd"] == pytest.approx(50.0, rel=1e-6)
        assert row["delta_vs_actual_usd"] == pytest.approx(0.0, abs=1e-6)

    def test_offset_zero_uses_actual_entry_not_bar_open(self):
        row = _get_row(self.results, 0)
        # bar 3 open = 101, but actual_entry = 100 → hypothetical_entry should be 100
        assert row["hypothetical_entry"] == pytest.approx(100.0, rel=1e-6)

    def test_earlier_entry_delta_minus_2(self):
        row = _get_row(self.results, -2)
        # bar 1 open = 99 → pnl=(105-99)*5*2=60, delta=+10
        assert row["hypothetical_entry"] == pytest.approx(99.0, rel=1e-6)
        assert row["pnl_usd"] == pytest.approx(60.0, rel=1e-6)
        assert row["delta_vs_actual_usd"] == pytest.approx(10.0, rel=1e-6)

    def test_earlier_entry_delta_minus_3(self):
        row = _get_row(self.results, -3)
        # bar 0 open = 98 → pnl=(105-98)*5*2=70, delta=+20
        assert row["hypothetical_entry"] == pytest.approx(98.0, rel=1e-6)
        assert row["pnl_usd"] == pytest.approx(70.0, rel=1e-6)
        assert row["delta_vs_actual_usd"] == pytest.approx(20.0, rel=1e-6)

    def test_later_entry_delta_plus_1(self):
        row = _get_row(self.results, 1)
        # bar 4 open = 102 → pnl=(105-102)*5*2=30, delta=-20
        assert row["hypothetical_entry"] == pytest.approx(102.0, rel=1e-6)
        assert row["pnl_usd"] == pytest.approx(30.0, rel=1e-6)
        assert row["delta_vs_actual_usd"] == pytest.approx(-20.0, rel=1e-6)

    def test_pnl_pct_offset_zero(self):
        row = _get_row(self.results, 0)
        # pct = (105-100)/100 = 0.05
        assert row["pnl_pct"] == pytest.approx(0.05, rel=1e-6)

    def test_all_offsets_present(self):
        returned_offsets = {r["offset_bars"] for r in self.results}
        assert returned_offsets == set(_OFFSETS)

    def test_long_side_aliases(self):
        for s in ("buy", "long", "buy_to_open", "BUY"):
            r = compute_entry_timing_scenarios(
                side=s,
                actual_entry_price=_ACTUAL_ENTRY,
                exit_price=_EXIT_LONG,
                bars_df=_BARS,
                entry_bar_index=_ENTRY_BAR_IDX,
                offsets=[0],
            )
            assert r[0]["pnl_usd"] == pytest.approx(5.0, rel=1e-6), f"failed for side={s!r}"


# ── SHORT tests ───────────────────────────────────────────────────────────────


class TestShort:
    """SHORT trade: entry=100, exit=95, multiplier=5, qty=2."""

    def setup_method(self):
        self.results = compute_entry_timing_scenarios(
            side="sell",
            actual_entry_price=_ACTUAL_ENTRY,
            exit_price=_EXIT_SHORT,
            bars_df=_BARS,
            entry_bar_index=_ENTRY_BAR_IDX,
            offsets=_OFFSETS,
            multiplier=_MULTIPLIER,
            qty=_QTY,
        )

    def test_offset_zero_reproduces_actual_pnl(self):
        row = _get_row(self.results, 0)
        # pnl = (100-95)*5*2 = 50.0
        assert row["pnl_usd"] == pytest.approx(50.0, rel=1e-6)
        assert row["delta_vs_actual_usd"] == pytest.approx(0.0, abs=1e-6)

    def test_earlier_entry_delta_minus_2(self):
        row = _get_row(self.results, -2)
        # bar 1 open=99 → pnl=(99-95)*5*2=40, delta=-10
        assert row["hypothetical_entry"] == pytest.approx(99.0, rel=1e-6)
        assert row["pnl_usd"] == pytest.approx(40.0, rel=1e-6)
        assert row["delta_vs_actual_usd"] == pytest.approx(-10.0, rel=1e-6)

    def test_later_entry_delta_plus_1(self):
        row = _get_row(self.results, 1)
        # bar 4 open=102 → pnl=(102-95)*5*2=70, delta=+20
        assert row["hypothetical_entry"] == pytest.approx(102.0, rel=1e-6)
        assert row["pnl_usd"] == pytest.approx(70.0, rel=1e-6)
        assert row["delta_vs_actual_usd"] == pytest.approx(20.0, rel=1e-6)

    def test_pnl_pct_offset_zero(self):
        row = _get_row(self.results, 0)
        # pct = (100-95)/100 = 0.05
        assert row["pnl_pct"] == pytest.approx(0.05, rel=1e-6)


# ── Edge-case tests ───────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_none_bars_returns_empty(self):
        result = compute_entry_timing_scenarios(
            "buy", 100.0, 105.0, None, 0, [0]
        )
        assert result == []

    def test_empty_dataframe_returns_empty(self):
        empty = pd.DataFrame(columns=["open", "high", "low"])
        result = compute_entry_timing_scenarios(
            "buy", 100.0, 105.0, empty, 0, [0]
        )
        assert result == []

    def test_missing_open_column_returns_empty(self):
        bad = pd.DataFrame({"close": [100.0, 101.0]})
        result = compute_entry_timing_scenarios(
            "buy", 100.0, 105.0, bad, 0, [0]
        )
        assert result == []

    def test_zero_entry_price_returns_empty(self):
        result = compute_entry_timing_scenarios(
            "buy", 0.0, 105.0, _BARS, 0, [0]
        )
        assert result == []

    def test_zero_exit_price_returns_empty(self):
        result = compute_entry_timing_scenarios(
            "buy", 100.0, 0.0, _BARS, 0, [0]
        )
        assert result == []

    def test_empty_offsets_returns_empty_list(self):
        result = compute_entry_timing_scenarios(
            "buy", 100.0, 105.0, _BARS, 3, []
        )
        assert result == []

    def test_out_of_range_negative_offset_clamped(self):
        # offset=-100 should clamp to index 0 (bar open=98)
        result = compute_entry_timing_scenarios(
            "buy", 100.0, 105.0, _BARS, 3, [-100]
        )
        assert len(result) == 1
        assert result[0]["hypothetical_entry"] == pytest.approx(98.0, rel=1e-6)

    def test_out_of_range_positive_offset_clamped(self):
        # offset=+100 should clamp to last bar (index 6, open=104)
        result = compute_entry_timing_scenarios(
            "buy", 100.0, 105.0, _BARS, 3, [100]
        )
        assert len(result) == 1
        assert result[0]["hypothetical_entry"] == pytest.approx(104.0, rel=1e-6)

    def test_single_offset_zero_only(self):
        result = compute_entry_timing_scenarios(
            "buy", 100.0, 105.0, _BARS, 3, [0], multiplier=5.0, qty=1.0
        )
        assert len(result) == 1
        row = result[0]
        assert row["offset_bars"] == 0
        assert row["delta_vs_actual_usd"] == pytest.approx(0.0, abs=1e-6)
        # pnl = (105-100)*5*1 = 25
        assert row["pnl_usd"] == pytest.approx(25.0, rel=1e-6)
