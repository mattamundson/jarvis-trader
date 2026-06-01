"""
Tests for analytics.paper_trade_pairing — FIFO round-trip matcher.

Regression tests to prevent the pnl-missing-multiplier bug from sneaking back.
All tests are offline, no DB, no engine required.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

# Ensure engine root is importable regardless of CWD
sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.paper_trade_pairing import (
    DEFAULT_MULTIPLIERS,
    ClosedRoundTrip,
    compute_metrics,
    pair_trades,
)

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(ts_str: str) -> str:
    """Return an ISO timestamp string (Z suffix) for a given datetime literal."""
    return ts_str


def _trade(
    symbol: str,
    side: str,
    filled_price: float,
    timestamp: str,
    quantity: float = 1.0,
    slippage_ticks: int = 0,
    pnl_override: float | None = None,
) -> dict:
    """Build a minimal trade dict resembling paper_trades.json entries."""
    t: dict = {
        "order_id": f"test-{side}-{timestamp}",
        "timestamp": timestamp,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "filled_price": filled_price,
        "trade_value": filled_price * quantity,
        "slippage_ticks": slippage_ticks,
        "is_futures": True,
        "is_options": False,
        # pnl_override simulates the writer's broken stored value
        "pnl": pnl_override,
    }
    return t


# ---------------------------------------------------------------------------
# test_pair_buy_then_sell_long_winning
# ---------------------------------------------------------------------------


def test_pair_buy_then_sell_long_winning():
    """
    Simple long: buy at 5300.0, sell at 5302.0.
    Expected PnL = (5302 - 5300) × 1 × MES_mult(5) = $10.00.
    The stored ``pnl`` on the sell record is intentionally wrong (writer bug
    value: raw diff with no mult) — the helper must ignore it.
    """
    raw = [
        _trade("MES", "buy", 5300.0, "2026-05-06T10:00:00Z"),
        # wrong stored_pnl = 2.0 (no mult applied) — should be ignored
        _trade("MES", "sell", 5302.0, "2026-05-06T10:05:00Z", pnl_override=2.0),
    ]
    closed = pair_trades(raw)

    assert len(closed) == 1
    rt = closed[0]
    assert rt.symbol == "MES"
    assert rt.side == "buy"
    assert rt.entry_price == 5300.0
    assert rt.exit_price == 5302.0
    assert rt.pnl == pytest.approx(10.0)
    assert rt.is_win is True


# ---------------------------------------------------------------------------
# test_pair_buy_then_sell_long_losing
# ---------------------------------------------------------------------------


def test_pair_buy_then_sell_long_losing():
    """
    Long: buy at 5300.0, sell at 5298.0.
    Expected PnL = (5298 - 5300) × 1 × 5 = -$10.00.
    """
    raw = [
        _trade("MES", "buy", 5300.0, "2026-05-06T10:00:00Z"),
        _trade("MES", "sell", 5298.0, "2026-05-06T10:05:00Z", pnl_override=-0.4),
    ]
    closed = pair_trades(raw)

    assert len(closed) == 1
    assert closed[0].pnl == pytest.approx(-10.0)
    assert closed[0].is_win is False


# ---------------------------------------------------------------------------
# test_pair_sell_then_buy_short_winning
# ---------------------------------------------------------------------------


def test_pair_sell_then_buy_short_winning():
    """
    Short-then-cover: sell at 5302.0, buy back at 5298.0.
    Expected PnL = (5302 - 5298) × 1 × 5 = $20.00.
    """
    raw = [
        _trade("MES", "sell", 5302.0, "2026-05-06T10:00:00Z"),
        _trade("MES", "buy", 5298.0, "2026-05-06T10:10:00Z"),
    ]
    closed = pair_trades(raw)

    assert len(closed) == 1
    rt = closed[0]
    assert rt.side == "sell"
    assert rt.entry_price == 5302.0
    assert rt.exit_price == 5298.0
    assert rt.pnl == pytest.approx(20.0)
    assert rt.is_win is True


# ---------------------------------------------------------------------------
# test_pair_multiple_positions_same_symbol_sequential
# ---------------------------------------------------------------------------


def test_pair_multiple_positions_same_symbol_sequential():
    """
    Two sequential MES round-trips on the same day.
    Trip 1: buy 5300 / sell 5301 → +$5
    Trip 2: buy 5301 / sell 5299 → -$10
    """
    raw = [
        _trade("MES", "buy",  5300.0, "2026-05-06T09:00:00Z"),
        _trade("MES", "sell", 5301.0, "2026-05-06T09:05:00Z"),
        _trade("MES", "buy",  5301.0, "2026-05-06T09:10:00Z"),
        _trade("MES", "sell", 5299.0, "2026-05-06T09:15:00Z"),
    ]
    closed = pair_trades(raw)

    assert len(closed) == 2
    pnls = sorted(rt.pnl for rt in closed)
    assert pnls[0] == pytest.approx(-10.0)
    assert pnls[1] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# test_pair_handles_unclosed_position
# ---------------------------------------------------------------------------


def test_pair_handles_unclosed_position():
    """
    The last buy has no matching sell — it must NOT appear in closed list.
    """
    raw = [
        _trade("MES", "buy",  5300.0, "2026-05-06T09:00:00Z"),
        _trade("MES", "sell", 5302.0, "2026-05-06T09:05:00Z"),
        # This buy is open at end of window — not a closed trade yet
        _trade("MES", "buy",  5303.0, "2026-05-06T09:10:00Z"),
    ]
    closed = pair_trades(raw)

    assert len(closed) == 1
    assert closed[0].pnl == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# test_pair_correct_multiplier_applied — MES vs MGC vs MCL
# ---------------------------------------------------------------------------


def test_pair_correct_multiplier_applied_mes():
    """MES multiplier = 5: 1-point move on 1 contract = $5."""
    raw = [
        _trade("MES", "buy",  5300.0, "2026-05-06T09:00:00Z"),
        _trade("MES", "sell", 5301.0, "2026-05-06T09:05:00Z"),
    ]
    closed = pair_trades(raw)
    assert closed[0].pnl == pytest.approx(1.0 * 1 * 5)


def test_pair_correct_multiplier_applied_mgc():
    """MGC multiplier = 10: 1-point move on 1 contract = $10."""
    raw = [
        _trade("MGC", "buy",  2000.0, "2026-05-06T09:00:00Z"),
        _trade("MGC", "sell", 2001.0, "2026-05-06T09:05:00Z"),
    ]
    closed = pair_trades(raw)
    assert closed[0].pnl == pytest.approx(1.0 * 1 * 10)


def test_pair_correct_multiplier_applied_mcl():
    """MCL multiplier = 100: 1-point move on 1 contract = $100."""
    raw = [
        _trade("MCL", "buy",  83.0, "2026-05-06T09:00:00Z"),
        _trade("MCL", "sell", 84.0, "2026-05-06T09:05:00Z"),
    ]
    closed = pair_trades(raw)
    assert closed[0].pnl == pytest.approx(1.0 * 1 * 100)


def test_pair_correct_multiplier_applied_mnq():
    """MNQ multiplier = 2: 1-point move on 1 contract = $2."""
    raw = [
        _trade("MNQ", "buy",  17500.0, "2026-05-06T09:00:00Z"),
        _trade("MNQ", "sell", 17501.0, "2026-05-06T09:05:00Z"),
    ]
    closed = pair_trades(raw)
    assert closed[0].pnl == pytest.approx(1.0 * 1 * 2)


# ---------------------------------------------------------------------------
# test_stored_pnl_is_ignored (anti-regression for the writer bug)
# ---------------------------------------------------------------------------


def test_stored_pnl_is_ignored():
    """
    Even when the sell entry has a wildly wrong stored pnl, the pairer must
    ignore it and compute from prices × multiplier.

    MES buy=5300, sell=5302 → correct = $10.
    stored_pnl on sell = 999.99 (simulating corrupted writer value).
    """
    raw = [
        _trade("MES", "buy",  5300.0, "2026-05-06T09:00:00Z"),
        _trade("MES", "sell", 5302.0, "2026-05-06T09:05:00Z", pnl_override=999.99),
    ]
    closed = pair_trades(raw)

    assert len(closed) == 1
    assert closed[0].pnl == pytest.approx(10.0), (
        "pair_trades must ignore the stored pnl field and recompute from prices"
    )


# ---------------------------------------------------------------------------
# test_compute_metrics_win_rate
# ---------------------------------------------------------------------------


def test_compute_metrics_win_rate():
    """compute_metrics returns correct win_rate for a 2W/1L set."""
    ts1 = datetime(2026, 5, 6, 10, 0, tzinfo=_UTC)
    ts2 = datetime(2026, 5, 6, 10, 5, tzinfo=_UTC)
    closed = [
        ClosedRoundTrip("MES", "buy", 1, 5300.0, 5302.0, ts1, ts2, pnl=10.0),
        ClosedRoundTrip("MES", "buy", 1, 5300.0, 5301.0, ts1, ts2, pnl=5.0),
        ClosedRoundTrip("MES", "buy", 1, 5302.0, 5300.0, ts1, ts2, pnl=-10.0),
    ]
    m = compute_metrics(closed)
    assert m["total_trades"] == 3
    assert m["wins"] == 2
    assert m["losses"] == 1
    assert m["win_rate"] == pytest.approx(2 / 3)
    assert m["total_pnl"] == pytest.approx(5.0)


def test_compute_metrics_empty():
    """compute_metrics on empty list returns safe defaults."""
    m = compute_metrics([])
    assert m["total_trades"] == 0
    assert m["win_rate"] is None
    assert m["total_pnl"] == 0.0


# ---------------------------------------------------------------------------
# test_today_actual_data — smoke test against the real paper_trades.json
# ---------------------------------------------------------------------------


def test_today_actual_data(tmp_path):
    """
    Smoke-test against the real engine/data/paper_trades.json.
    At least one round-trip must be closed, and win_rate must be a valid float.

    This test is skipped gracefully if the file is missing (CI / clean clone).
    """
    json_path = Path(__file__).parent.parent / "data" / "paper_trades.json"
    if not json_path.exists():
        pytest.skip("paper_trades.json not found — skipping live-data smoke test")

    import json

    raw_data = json.loads(json_path.read_text(encoding="utf-8"))
    if isinstance(raw_data, dict):
        raw_trades = raw_data.get("trades", [])
    else:
        raw_trades = raw_data

    closed = pair_trades(raw_trades)

    # Basic sanity: if we have any sells, we expect at least some closed pairs
    sell_count = sum(1 for t in raw_trades if (t.get("side") or "").lower() in ("sell", "sell_to_close"))
    if sell_count == 0:
        pytest.skip("No sell entries in paper_trades.json yet — nothing to pair")

    assert len(closed) > 0, "Expected at least one closed round-trip from the sell entries"

    m = compute_metrics(closed)
    assert m["total_trades"] == len(closed)
    assert isinstance(m["win_rate"], float), "win_rate must be a float, not None, when trades exist"
    assert 0.0 <= m["win_rate"] <= 1.0

    # Print a summary for diagnostic visibility when test is run with -v
    print(
        f"\n[paper_trade_pairing smoke] "
        f"closed={m['total_trades']} wins={m['wins']} losses={m['losses']} "
        f"win_rate={m['win_rate'] * 100:.1f}% total_pnl=${m['total_pnl']:+.2f} "
        f"biggest_win=${m['biggest_win'] or 0:+.2f} biggest_loss=${m['biggest_loss'] or 0:+.2f}"
    )
