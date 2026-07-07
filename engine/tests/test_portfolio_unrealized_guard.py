"""Guard against contaminated entry prices poisoning unrealized P&L.

Regression for the 2026-06-12 phantom-aggregate bug: a paper MES position was
opened at the IB snapshot sentinel price (100.5) instead of a real fill. With a
real current price (~7414), `_compute_unrealized` fabricated +$36,568 of
unrealized P&L, which propagated into `/portfolio/summary.total_daily_pnl`
($38,851 vs the truthful $1,291). The dashboard reported a 7770%-of-target day.

The fix: `_compute_unrealized` must flag an implausible entry (the 100.5
sentinel, a non-positive entry, or an entry that diverges from the current price
by an extreme factor) and refuse to emit a phantom `unrealized_pnl` — so a
single corrupt position can never poison the portfolio aggregate. The position
is still returned and flagged (surfaced, not silently dropped).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from routers.portfolio_router import (  # noqa: E402
    _IB_SNAPSHOT_SENTINEL,
    INSTRUMENT_POINT_VALUES,
    _compute_unrealized,
    _mark_is_suspect,
)


def _pos(symbol: str, entry: float, action: str = "buy", qty: float = 1.0) -> dict:
    return {
        "symbol": symbol,
        "action": action,
        "quantity": qty,
        "entry_price": entry,
        "trade_id": "t1",
    }


def test_sentinel_entry_does_not_produce_phantom_pnl():
    """MES opened at the 100.5 sentinel with a real ~7414 mark must NOT report
    a ~$36k unrealized P&L."""
    pos = _pos("MES", entry=_IB_SNAPSHOT_SENTINEL)
    out = _compute_unrealized(pos, 7414.25, INSTRUMENT_POINT_VALUES)
    assert out["entry_suspect"] is True
    # No phantom: P&L is suppressed (None), so callers' `or 0.0` excludes it.
    assert out["unrealized_pnl"] is None


def test_extreme_divergence_entry_flagged():
    """Any entry that diverges from the current mark by >5x is contamination."""
    pos = _pos("MES", entry=50.0)  # vs a ~5300 mark -> ~106x
    out = _compute_unrealized(pos, 5300.0, INSTRUMENT_POINT_VALUES)
    assert out["entry_suspect"] is True
    assert out["unrealized_pnl"] is None


def test_nonpositive_entry_flagged():
    pos = _pos("MGC", entry=0.0)
    out = _compute_unrealized(pos, 4180.0, INSTRUMENT_POINT_VALUES)
    assert out["entry_suspect"] is True
    assert out["unrealized_pnl"] is None


def test_valid_position_is_untouched():
    """Regression guard: a real MGC position keeps its correct P&L and is NOT
    flagged. entry 4083.4 -> current 4182.2, point value $10 -> +$988."""
    pos = _pos("MGC", entry=4083.4)
    out = _compute_unrealized(pos, 4182.2, INSTRUMENT_POINT_VALUES)
    assert out["entry_suspect"] is False
    assert out["unrealized_pnl"] is not None
    assert abs(out["unrealized_pnl"] - 988.0) < 1.0


def test_no_current_price_is_not_suspect():
    """A missing mark is not contamination — it just yields no P&L."""
    pos = _pos("MES", entry=5300.0)
    out = _compute_unrealized(pos, None, INSTRUMENT_POINT_VALUES)
    assert out["entry_suspect"] is False
    assert out["unrealized_pnl"] is None


# ── Mark-plausibility guard (2026-06-16 live phantom) ─────────────────────────
# The entry can be a perfectly valid fill while the *mark* is the data error.
# A live MES short opened at 5299.875 received a mark of 7521.75 (+41.9%) — a
# wrong-scale / stale tick, not a real intraday move. At $5/point that fabricated
# -$11,109 unrealized and poisoned /portfolio/summary.total_daily_pnl
# (-$11,116 vs the truthful realized -$16.13). The 5x entry-divergence guard
# missed it (7521/5299 = 1.42x). A mark implying an implausible move from the
# entry must be flagged and must not drive unrealized P&L.


def test_implausible_mark_does_not_produce_phantom_pnl():
    """The exact live bug: valid MES short fill, +41.9% bad mark -> no phantom."""
    pos = _pos("MES", entry=5299.875, action="sell")
    out = _compute_unrealized(pos, 7521.75, INSTRUMENT_POINT_VALUES)
    assert out["entry_suspect"] is False  # the ENTRY is a real fill
    assert out["mark_suspect"] is True  # the MARK is the data error
    assert out["unrealized_pnl"] is None  # suppressed -> caller's `or 0.0` excludes it


def test_mark_is_suspect_helper():
    assert _mark_is_suspect(5299.875, 7521.75) is True  # +41.9% -> data error
    assert _mark_is_suspect(4311.1, 4311.1) is False  # exact mark
    assert _mark_is_suspect(100.0, 110.0) is False  # a real ~10% move is fine
    assert _mark_is_suspect(5300.0, 0.0) is True  # non-positive mark
    assert _mark_is_suspect(5300.0, -1.0) is True
    assert _mark_is_suspect(5300.0, None) is False  # absence handled separately


def test_real_moderate_move_keeps_pnl():
    """Regression: a believable intraday move keeps its P&L and is not flagged.
    MES short 5300 -> 5290 (-0.19%), $5 point value -> +$50."""
    pos = _pos("MES", entry=5300.0, action="sell")
    out = _compute_unrealized(pos, 5290.0, INSTRUMENT_POINT_VALUES)
    assert out["mark_suspect"] is False
    assert out["unrealized_pnl"] is not None
    assert abs(out["unrealized_pnl"] - 50.0) < 0.01


# ── Stale-mark guard (2026-06-16 phantom-aggregate bug) ──────────────────────
# With the IBKR data leg degraded, get_tick_price fell through to the Tier-5
# csv_cache last *daily* close: MGC was marked ~3757 against a fresh ~4311 entry,
# fabricating ~-$11,076 unrealized that poisoned /portfolio/summary
# (total_daily_pnl -$11,092 vs the truthful realized -$16). The entry was NOT
# suspect (real fill, <5x divergence) — the *mark* was stale, so the fix gates on
# the get_tick_price source tag, not on a magnitude threshold.


def test_stale_csv_cache_mark_does_not_produce_phantom_pnl():
    """The exact live case: MGC LONG 2 @ 4311.1 marked from a stale csv_cache
    close (~3757) must NOT report ~-$11k unrealized."""
    pos = _pos("MGC", entry=4311.1, action="buy", qty=2.0)
    out = _compute_unrealized(pos, 3757.3, INSTRUMENT_POINT_VALUES, mark_source="csv_cache")
    assert out["entry_suspect"] is False  # the entry is a real fill
    assert out["mark_stale"] is True
    assert out["unrealized_pnl"] is None
    assert out["mark_source"] == "csv_cache"


def test_expired_and_historical_marks_flagged_stale():
    for src in ("polygon_cache_expired", "ibkr_historical", "unavailable"):
        out = _compute_unrealized(
            _pos("MGC", entry=4311.1, qty=2.0), 3757.3, INSTRUMENT_POINT_VALUES, mark_source=src
        )
        assert out["mark_stale"] is True, src
        assert out["unrealized_pnl"] is None, src


def test_fresh_source_computes_pnl_normally():
    """A live IBKR mark is trusted: MGC 4311.1 -> 4320.0, $10/pt, 2 lots -> +$178."""
    pos = _pos("MGC", entry=4311.1, action="buy", qty=2.0)
    out = _compute_unrealized(pos, 4320.0, INSTRUMENT_POINT_VALUES, mark_source="ibkr")
    assert out["mark_stale"] is False
    assert out["unrealized_pnl"] is not None
    assert abs(out["unrealized_pnl"] - 178.0) < 1.0


def test_unknown_source_is_not_stale_backward_compat():
    """No source (the legacy 3-arg call) must behave exactly as before."""
    pos = _pos("MES", entry=5300.0, action="sell")
    out = _compute_unrealized(pos, 5290.0, INSTRUMENT_POINT_VALUES)
    assert out["mark_stale"] is False
    assert out["unrealized_pnl"] is not None  # (5300-5290)*5 = +50


def test_stale_mark_excluded_from_aggregate_sum():
    """Mirror the /portfolio/summary loop: only fresh marks sum into the
    unrealized aggregate; the stale leg's phantom never enters it."""
    fresh = _compute_unrealized(
        _pos("MES", entry=5300.0, action="sell"),
        5290.0,
        INSTRUMENT_POINT_VALUES,
        mark_source="ibkr",
    )
    stale = _compute_unrealized(
        _pos("MGC", entry=4311.1, action="buy", qty=2.0),
        3757.3,
        INSTRUMENT_POINT_VALUES,
        mark_source="csv_cache",
    )
    # the summary loop does `upnl = computed.get("unrealized_pnl") or 0.0`
    agg = (fresh.get("unrealized_pnl") or 0.0) + (stale.get("unrealized_pnl") or 0.0)
    stale_count = sum(1 for c in (fresh, stale) if c.get("mark_stale"))
    assert abs(agg - 50.0) < 1e-6  # only the fresh MES short: (5300-5290)*5
    assert stale_count == 1
    assert stale["unrealized_pnl"] is None  # phantom -$11k excluded
