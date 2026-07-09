"""Cross-source P&L agreement guard (T1-08 trap-detector).

At least three independently-coded realized-P&L pipelines have coexisted in this
system with no cross-check: ``engine/analytics/pnl_truth.py``,
``PortfolioTracker.get_performance()`` (``engine/portfolio/tracker.py``), and an
external ``master-api`` service (out of repo scope). Journal, Scorecard,
Performance, and Command-Center dashboard tiles could each render a DIFFERENT
total for the identical trade history.

The immediate root cause — duplicate open-state rows from an hourly review job
re-emitting every open position with a fresh idempotency key — was fixed by the
open-state INSERT guard (PR #299, ``engine/database/_mixins_trades.py``
``insert_paper_trade``) and hardened by the commission/multiplier/drawdown pass
(PR #304). ``test_paper_trade_open_state_dedup.py`` pins that fix directly.

This file is the SEPARATE, PERMANENT guard the dedup fix does not cover: even
with zero duplicate rows, two independently-coded aggregators reading the same
``paper_trades`` table can still disagree (different status filters, different
rounding, one forgetting commission, one mis-handling an open leg, etc). Build
one fixed fixture trade history through the REAL ``PortfolioTracker`` code path
(so dedup/commission/multiplier all apply exactly as in production), then assert
``pnl_truth.py``'s independent calculation and ``PortfolioTracker.
get_performance()`` agree to the cent against the SAME underlying table. Keep
this test green forever — it is the tripwire for this whole bug class
recurring, not a one-time regression pin.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from analytics.pnl_truth import compute_pnl_truth, pnl_truth_from_sqlite
from database.manager import DatabaseManager
from portfolio.tracker import PortfolioTracker

# Commission is pinned in every fixture below so the expected totals are
# deterministic regardless of the shell's COMMISSION_PER_CONTRACT.
_COMMISSION = 1.50


def _build_fixture_tracker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[PortfolioTracker, DatabaseManager, float]:
    """Build a fixed trade history through the REAL open_trade/close_trade code
    path (not hand-rolled SQL — a hand-inserted fixture could accidentally
    sidestep the exact bugs this test exists to catch) and return the expected
    total realized P&L computed independently in this helper.

    Trades:
      1. MES buy 2 @ 7400.00 -> 7420.00   : (7420-7400)*2*5   - 2*1.50 = 197.00
      2. MGC sell 1 @ 5591.00 -> 5601.00  : (5591-5601)*1*10  - 1*1.50 = -101.50
      3. MES buy 1 @ 7500.00, RE-LOGGED at 7502.00 (distinct idempotency key,
         same still-open (symbol, side) -- the T1-08 over-count trigger) before
         closing @ 7510.00 : (7510-7500)*1*5 - 1*1.50 = 48.50
      4. MGC buy 1 @ 5600.00, left OPEN -- must not leak into either realized total.
    """
    monkeypatch.setenv("COMMISSION_PER_CONTRACT", str(_COMMISSION))
    monkeypatch.delenv("ALLOW_DEFAULT_MULTIPLIER", raising=False)

    db_path = tmp_path / "cross_source.db"
    db = DatabaseManager(str(db_path))
    db.initialize()
    tracker = PortfolioTracker(store_path=tmp_path / "trades.jsonl", db_manager=db)

    tid1 = tracker.open_trade("MES", "buy", 2, 7400.00)
    tracker.close_trade(tid1, 7420.00)

    tid2 = tracker.open_trade("MGC", "sell", 1, 5591.00)
    tracker.close_trade(tid2, 5601.00)

    tid3 = tracker.open_trade("MES", "buy", 1, 7500.00)
    tid3_relog = tracker.open_trade("MES", "buy", 1, 7502.00)
    assert tid3_relog == tid3, (
        "open-state guard must collapse the re-log to the existing open row "
        "(T1-08 over-count regression) -- got a distinct trade_id instead"
    )
    tracker.close_trade(tid3, 7510.00)

    tracker.open_trade("MGC", "buy", 1, 5600.00)  # left open on purpose

    expected_total = 197.00 + (-101.50) + 48.50  # = 144.00
    return tracker, db, expected_total


def test_pnl_truth_and_tracker_agree_to_the_cent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mandated cross-check: pnl_truth.py and PortfolioTracker.get_performance()
    must agree to the cent on the identical fixture trade history."""
    tracker, db, expected_total = _build_fixture_tracker(tmp_path, monkeypatch)

    tracker_total = tracker.get_performance()["total_pnl"]
    assert round(tracker_total, 2) == round(expected_total, 2)

    truth = pnl_truth_from_sqlite(db._db_path)
    assert truth.trusted, f"pnl_truth degraded unexpectedly: {truth.reasons}"
    assert round(truth.realized_pnl, 2) == round(expected_total, 2)

    # The actual cross-surface guard: agreement with EACH OTHER, not just with
    # the hand-computed constant above.
    assert round(truth.realized_pnl, 2) == round(tracker_total, 2), (
        f"pnl_truth={truth.realized_pnl!r} vs tracker.get_performance()="
        f"{tracker_total!r} -- two P&L surfaces disagree on the same trade history"
    )

    # Also exercise pnl_truth's OWN built-in cross-source tolerance check (it
    # was designed for exactly this comparison) so a future change that breaks
    # it is caught here, not silently in production.
    rows = db.get_closed_trades(limit=10000)
    truth_cross = compute_pnl_truth(rows, cross_source_pnl=tracker_total)
    assert truth_cross.trusted, f"cross-source divergence check failed: {truth_cross.reasons}"


def test_open_position_excluded_from_both_realized_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A currently-open leg must not leak into either pipeline's realized P&L,
    and both pipelines must agree on the closed-trade count."""
    tracker, db, _expected_total = _build_fixture_tracker(tmp_path, monkeypatch)

    perf = tracker.get_performance()
    assert perf["num_open"] == 1  # the untouched MGC buy left open in the fixture
    assert perf["num_trades"] == 3  # MES win, MGC loss, MES relog-collapsed win

    truth = pnl_truth_from_sqlite(db._db_path)
    assert truth.closed_trades == 3
    assert truth.closed_trades == perf["num_trades"]


def test_divergent_sources_are_caught_not_silently_trusted() -> None:
    """Negative control: compute_pnl_truth's cross-source guard must actually
    fire on a genuine mismatch, so a future refactor that quietly disables the
    tolerance check cannot pass this file by accident."""
    rows = [{"status": "closed", "pnl": 100.0}, {"status": "closed", "pnl": -20.0}]
    truth = compute_pnl_truth(rows, cross_source_pnl=999.0)
    assert not truth.trusted
    assert any(r.startswith("source_divergence") for r in truth.reasons)
