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
