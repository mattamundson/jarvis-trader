"""End-to-end numeric-accuracy test harness (US-101).

Project CLAUDE.md names this gap explicitly: "there is currently no
end-to-end numeric-accuracy test (engine -> proxy -> render)." A dashboard
that renders a confidently wrong P&L, position size, or drawdown is worse
than one that's visibly offline -- Amo trades on the number, not the uptime.

This module is the harness that closes that gap. Every assertion here checks
a value against a HAND-COMPUTED expected number (not "runs without error"),
and at least one metric per category is read through two independently-coded
paths so a silent divergence between them fails the suite instead of shipping
to a dashboard tile.

Layout:
  1. P&L        -- real PortfolioTracker+SQLite code path, hand-computed
                   per-trade and portfolio-total expectations.
  2. Position size -- engine/utils/position_sizing.py pure-function fixtures.
  3. Drawdown   -- engine/analytics/trade_analytics.py hand-computed equity
                   curves, including the DB-sourced trade sequence from (1).
  4. Cross-check -- the mandated round-trip: a raw SQL SUM(pnl) read of the
     same paper_trades rows vs analytics.trade_analytics.calculate_analytics()
     aggregating the same rows fetched via the DB API. These are two
     independently-coded readers of identical underlying data; any drift
     between them is a bug, not a rounding preference.

This file intentionally does NOT re-implement engine/tests/test_pnl_cross_
source_agreement.py's pnl_truth-vs-tracker guard -- that comparison already
exists and stays green. The new comparison here (raw SQL vs the trade_
analytics aggregation layer) is a third, previously-untested reader.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from analytics.trade_analytics import (
    DEFAULT_STARTING_CAPITAL,
    calculate_analytics,
    calculate_max_drawdown,
)
from database.manager import DatabaseManager
from portfolio.tracker import PortfolioTracker
from utils.position_sizing import calculate_position_size

# Commission pinned so expected totals are deterministic regardless of the
# shell's COMMISSION_PER_CONTRACT.
_COMMISSION = 1.50


@pytest.fixture()
def fixture_tracker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[PortfolioTracker, DatabaseManager, float]:
    """Three closed trades through the REAL open_trade/close_trade code path
    (not hand-inserted SQL, so multiplier/commission/idempotency logic all
    apply exactly as in production), plus their hand-computed expected P&L.

    Trade A: MES buy 1 @ 5000.00 -> 5010.00
      gross = (5010-5000) * 1 * 5   =  50.00
      pnl   = 50.00 - 1*1.50        =  48.50

    Trade B: MGC sell 2 @ 2000.00 -> 1990.00
      gross = (2000-1990) * 2 * 10  = 200.00
      pnl   = 200.00 - 2*1.50       = 197.00

    Trade C: MCL buy 3 @ 70.00 -> 69.00 (loss)
      gross = (69-70) * 3 * 100     = -300.00
      pnl   = -300.00 - 3*1.50      = -304.50

    Portfolio total = 48.50 + 197.00 - 304.50 = -59.00
    """
    monkeypatch.setenv("COMMISSION_PER_CONTRACT", str(_COMMISSION))
    monkeypatch.delenv("ALLOW_DEFAULT_MULTIPLIER", raising=False)

    db_path = tmp_path / "numeric_accuracy.db"
    db = DatabaseManager(str(db_path))
    db.initialize()
    tracker = PortfolioTracker(store_path=tmp_path / "trades.jsonl", db_manager=db)

    tid_a = tracker.open_trade("MES", "buy", 1, 5000.00)
    trade_a = tracker.close_trade(tid_a, 5010.00)
    assert trade_a.pnl == pytest.approx(48.50)

    tid_b = tracker.open_trade("MGC", "sell", 2, 2000.00)
    trade_b = tracker.close_trade(tid_b, 1990.00)
    assert trade_b.pnl == pytest.approx(197.00)

    tid_c = tracker.open_trade("MCL", "buy", 3, 70.00)
    trade_c = tracker.close_trade(tid_c, 69.00)
    assert trade_c.pnl == pytest.approx(-304.50)

    expected_total = 48.50 + 197.00 + (-304.50)  # = -59.00
    assert expected_total == pytest.approx(-59.00)

    return tracker, db, expected_total


# ── 1. P&L: hand-computed per-trade and portfolio-total fixtures ─────────────


class TestPnlHandComputed:
    def test_per_trade_pnl_matches_hand_computation(
        self, fixture_tracker: tuple[PortfolioTracker, DatabaseManager, float]
    ) -> None:
        tracker, db, _expected_total = fixture_tracker
        rows = {r["symbol"]: r for r in db.get_closed_trades(limit=10000)}
        assert rows["MES"]["pnl"] == pytest.approx(48.50)
        assert rows["MGC"]["pnl"] == pytest.approx(197.00)
        assert rows["MCL"]["pnl"] == pytest.approx(-304.50)

    def test_portfolio_total_matches_hand_computation(
        self, fixture_tracker: tuple[PortfolioTracker, DatabaseManager, float]
    ) -> None:
        tracker, _db, expected_total = fixture_tracker
        perf = tracker.get_performance()
        assert perf["num_trades"] == 3
        assert round(perf["total_pnl"], 2) == round(expected_total, 2)


# ── 2. Position size: pure-function hand-computed fixtures ───────────────────


class TestPositionSizeHandComputed:
    def test_mes_clamps_at_max_contracts(self) -> None:
        # risk_per_trade = 10000*0.01 = 100.00
        # stop_distance  = 10.0*0.70  = 7.00
        # $/contract     = 7.00*5     = 35.00  (MES multiplier = 5)
        # raw_contracts  = floor(100/35) = 2 -> clamp(2, 1, 2) = 2
        result = calculate_position_size(
            symbol="MES",
            account_value=10_000.0,
            atr=10.0,
            risk_pct=0.01,
            atr_stop_multiplier=0.70,
            max_contracts=2,
        )
        assert result.risk_per_trade == pytest.approx(100.00)
        assert result.stop_distance == pytest.approx(7.00)
        assert result.dollar_risk_per_contract == pytest.approx(35.00)
        assert result.contracts == 2

    def test_mgc_raw_contracts_clamped_down_to_max(self) -> None:
        # risk_per_trade = 100.00
        # stop_distance  = 1.0*0.70 = 0.70
        # $/contract     = 0.70*10  = 7.00   (MGC multiplier = 10)
        # raw_contracts  = floor(100/7) = 14 -> clamp(14, 1, 2) = 2
        result = calculate_position_size(
            symbol="MGC",
            account_value=10_000.0,
            atr=1.0,
            risk_pct=0.01,
            atr_stop_multiplier=0.70,
            max_contracts=2,
        )
        assert result.dollar_risk_per_contract == pytest.approx(7.00)
        assert result.contracts == 2

    def test_mcl_raw_contracts_clamped_up_to_one(self) -> None:
        # risk_per_trade = 5000*0.01 = 50.00
        # stop_distance  = 2.0*0.70  = 1.40
        # $/contract     = 1.40*100  = 140.00  (MCL multiplier = 100)
        # raw_contracts  = floor(50/140) = 0 -> clamp(0, 1, 2) = 1
        result = calculate_position_size(
            symbol="MCL",
            account_value=5_000.0,
            atr=2.0,
            risk_pct=0.01,
            atr_stop_multiplier=0.70,
            max_contracts=2,
        )
        assert result.dollar_risk_per_contract == pytest.approx(140.00)
        assert result.contracts == 1

    def test_small_account_fallback_is_one_contract_zero_risk(self) -> None:
        result = calculate_position_size(
            symbol="MES", account_value=999.99, atr=10.0, max_contracts=2
        )
        assert result.contracts == 1
        assert result.risk_per_trade == pytest.approx(0.0)

    def test_missing_atr_fallback_is_one_contract_nonzero_risk_budget(self) -> None:
        # risk budget is still computed (10000*0.01=100) even though sizing
        # itself falls back to 1 contract for lack of a stop distance.
        result = calculate_position_size(symbol="MES", account_value=10_000.0, atr=None)
        assert result.contracts == 1
        assert result.risk_per_trade == pytest.approx(100.00)
        assert result.dollar_risk_per_contract == pytest.approx(0.0)


# ── 3. Drawdown: hand-computed equity-curve fixtures ──────────────────────────


class TestDrawdownHandComputed:
    def test_floored_denominator_case(self) -> None:
        # Peak never exceeds DEFAULT_STARTING_CAPITAL, so the denominator
        # floors at 10,000 for every step (T0-03 fix).
        #   step   peak    equity   dd = (peak-equity)/10000
        #   500     500     500      0.0
        #   -200    500    -200      700/10000  = 0.07
        #   300     500     300      200/10000  = 0.02
        #   -800    500    -800     1300/10000  = 0.13   <- max
        equity_curve = [0.0, 500.0, -200.0, 300.0, -800.0]
        dd = calculate_max_drawdown(equity_curve)
        assert dd == pytest.approx(13.0, rel=1e-6)

    def test_real_peak_denominator_case(self) -> None:
        # Peak (15,000) exceeds DEFAULT_STARTING_CAPITAL, so the true peak is
        # the denominator, not the floor.
        #   peak=15000 at step1; dd = (15000-9000)/15000 = 0.40
        equity_curve = [0.0, 15_000.0, 9_000.0]
        dd = calculate_max_drawdown(equity_curve)
        assert dd == pytest.approx(40.0, rel=1e-6)
        assert DEFAULT_STARTING_CAPITAL < 15_000.0  # sanity: real-peak branch, not floor

    def test_drawdown_from_real_trade_sequence(
        self, fixture_tracker: tuple[PortfolioTracker, DatabaseManager, float]
    ) -> None:
        """Same drawdown formula, but the equity curve is built from the
        REAL closed-trade DB rows of fixture_tracker (chronological order),
        not a hand-typed list -- proves the engine -> DB -> analytics chain
        produces the hand-computable answer, not just the pure function in
        isolation.

        Chronological pnl sequence: +48.50, +197.00, -304.50
        equity curve: [0, 48.50, 245.50, -59.00]
          peak=48.50 -> dd=0
          peak=245.50 -> dd=0
          equity=-59.00, peak stays 245.50, denom=10000 (floored)
            dd = (245.50 - (-59.00)) / 10000 = 304.50/10000 = 0.03045 -> 3.045%
        """
        _tracker, db, _expected_total = fixture_tracker
        rows = sorted(db.get_closed_trades(limit=10000), key=lambda r: r["exit_time"])
        pnls = [r["pnl"] for r in rows]
        assert pnls == pytest.approx([48.50, 197.00, -304.50])

        equity = 0.0
        curve = [equity]
        for p in pnls:
            equity += p
            curve.append(equity)
        assert curve == pytest.approx([0.0, 48.50, 245.50, -59.00])

        dd = calculate_max_drawdown(curve)
        assert dd == pytest.approx(3.045, rel=1e-6)


# ── 4. Mandated cross-check: DB row read vs analytics-layer aggregation ──────


class TestPnlCrossCheckDbVsAnalyticsLayer:
    """The core (b) requirement: the SAME underlying paper_trades rows read
    two independently-coded ways must agree to the cent.

      Path 1 -- raw SQL SUM(pnl) directly against the sqlite file (no Python
                aggregation logic at all, just the database's own arithmetic).
      Path 2 -- analytics.trade_analytics.calculate_analytics(), a completely
                separate aggregation implementation, fed the same rows via
                DatabaseManager.get_closed_trades().

    Round-trip drift between these two is a bug per project rules (CLAUDE.md
    "Numeric accuracy is a first-class verification target"), not cosmetic.
    """

    def test_raw_sql_sum_matches_analytics_layer_aggregation(
        self, fixture_tracker: tuple[PortfolioTracker, DatabaseManager, float]
    ) -> None:
        _tracker, db, expected_total = fixture_tracker

        # Path 1: raw SQL read, bypassing every Python aggregation helper.
        con = sqlite3.connect(str(db._db_path))
        try:
            raw_sql_total = con.execute(
                "SELECT SUM(pnl) FROM paper_trades WHERE status='closed'"
            ).fetchone()[0]
        finally:
            con.close()

        # Path 2: the analytics-layer aggregator, fed the DB API's own rows.
        db_rows = db.get_closed_trades(limit=10000)
        analytics = calculate_analytics(db_rows)

        assert round(raw_sql_total, 2) == round(expected_total, 2)
        assert round(analytics.total_pnl, 2) == round(expected_total, 2)

        # The actual cross-surface guard: agreement with EACH OTHER, not just
        # with the hand-computed constant above.
        assert round(raw_sql_total, 2) == round(analytics.total_pnl, 2), (
            f"raw SQL SUM(pnl)={raw_sql_total!r} vs "
            f"calculate_analytics().total_pnl={analytics.total_pnl!r} -- two "
            f"independent readers of the identical paper_trades rows disagree"
        )

    def test_raw_sql_sum_matches_analytics_layer_win_rate_inputs(
        self, fixture_tracker: tuple[PortfolioTracker, DatabaseManager, float]
    ) -> None:
        """Second cross-checked metric on the same fixture: win/loss counts.
        Raw SQL COUNT(...) vs the analytics layer's win_rate-derived count."""
        _tracker, db, _expected_total = fixture_tracker

        con = sqlite3.connect(str(db._db_path))
        try:
            raw_wins = con.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE status='closed' AND pnl > 0"
            ).fetchone()[0]
            raw_total = con.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE status='closed'"
            ).fetchone()[0]
        finally:
            con.close()

        db_rows = db.get_closed_trades(limit=10000)
        analytics = calculate_analytics(db_rows)
        analytics_wins = round(analytics.win_rate / 100.0 * analytics.total_trades)

        assert raw_total == 3
        assert raw_wins == 2  # MES win, MGC win, MCL loss
        assert analytics.total_trades == raw_total
        assert analytics_wins == raw_wins
