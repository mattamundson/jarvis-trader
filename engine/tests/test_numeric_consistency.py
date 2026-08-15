"""
JARVIS TRADER — Engine-Internal Numeric Consistency Harness
==============================================================
Closes the ENGINE-INTERNAL half of the "no end-to-end numeric-accuracy test"
gap named in the repo CLAUDE.md: this file does not touch the dashboard or
any HTTP boundary. It cross-checks numeric formulas that are computed in
MORE THAN ONE PLACE inside `engine/` and that are supposed to agree, so a
silent divergence between two "the same" numbers is caught by CI instead of
by a human noticing a suspicious dashboard tile (the exact failure class this
session already found once: a Sharpe ratio computed two different,
disagreeing ways in two different files).

Every cross-check below was verified by READING both implementations first
(not assumed from a spec). Where two "similar-sounding" numbers turned out to
measure genuinely different things (single-sample percentile VaR vs.
bootstrap-resampled VaR), the test asserts a documented tolerance band
instead of forcing false equality. Where a real, live divergence was found
(the wfe_router weekly-snapshot Sharpe), it is captured as an `xfail` with a
comment describing the exact root cause, not silently skipped.

Synthetic fixture (deterministic, no RNG/seed dependency for anything except
the *bootstrap CI width* itself, which is inherently probabilistic and only
used for a loose sanity band):

    PNLS = [100, -50, 200, -80, 150, -30, 90, -40, 120, -60]

Hand-verifiable properties of this fixture (n=10 trades):
    wins   = [100, 200, 150, 90, 120]  -> 5 trades, gross_profit = 660
    losses = [-50, -80, -30, -40, -60] -> 5 trades, gross_loss   = 260 (abs)
    win_rate            = 5 / 10               = 0.5
    avg_win             = 660 / 5               = 132.0
    avg_loss (signed)   = -260 / 5               = -52.0
    payoff ratio R      = 132 / 52               = 2.5384615384615383
    raw Kelly f*        = (0.5*R - 0.5) / R      = 0.30303030303030304
    half-Kelly          = f* / 2                = 0.15151515151515152
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pytest

from agents.strategy_metrics import compute_recent_risk_metrics
from backtest.metrics import calculate_metrics, compute_kelly_fraction
from backtest.monte_carlo import compute_cvar, compute_var
from backtest.trade_manager import BacktestResult, Trade
from options import greeks_monitor as gm
from options import premium_calculator as pc
from risk.position_sizer import kelly_fraction as risk_kelly_fraction
from routers.wfe_router import _compute_snapshot_stats
from utils.position_sizing import calculate_half_kelly_size

# ---------------------------------------------------------------------------
# Shared synthetic fixture
# ---------------------------------------------------------------------------

PNLS = [100.0, -50.0, 200.0, -80.0, 150.0, -30.0, 90.0, -40.0, 120.0, -60.0]
INITIAL_CAPITAL = 10_000.0


def _make_backtest_result(pnls: list[float], initial_capital: float = INITIAL_CAPITAL) -> BacktestResult:
    """Build a real BacktestResult + Trade list and run it through the
    CANONICAL metrics pipeline (`calculate_metrics`), exactly the way
    backtester.py does after a run."""
    trades = [
        Trade(
            entry_date=datetime(2026, 1, 1) + timedelta(days=i),
            symbol="TESTX",
            direction="long" if pnl >= 0 else "short",
            entry_price=100.0,
            stop_price=95.0,
            target_1=105.0,
            target_2=110.0,
            contracts=1,
            multiplier=1.0,
            pnl=pnl,
        )
        for i, pnl in enumerate(pnls)
    ]
    equity_curve = [initial_capital]
    running = initial_capital
    for pnl in pnls:
        running += pnl
        equity_curve.append(running)

    result = BacktestResult(
        symbol="TESTX",
        start_date="2026-01-01",
        end_date="2026-01-10",
        initial_capital=initial_capital,
        final_capital=equity_curve[-1],
        trades=trades,
        equity_curve=equity_curve,
    )
    calculate_metrics(result)
    return result


def _make_paper_trades_db(pnls: list[float], symbol: str, week_start: str) -> sqlite3.Connection:
    """In-memory sqlite DB with the same `paper_trades` schema used in
    production / test_wfe_router.py, seeded with the synthetic pnl list as
    closed trades inside the given week."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE paper_trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id        TEXT    NOT NULL UNIQUE,
            symbol          TEXT    NOT NULL,
            side            TEXT    NOT NULL,
            quantity        REAL    NOT NULL,
            entry_price     REAL    NOT NULL,
            exit_price      REAL,
            entry_time      TEXT    NOT NULL,
            exit_time       TEXT,
            pnl             REAL,
            status          TEXT    NOT NULL DEFAULT 'open'
        )
        """
    )
    base = datetime.fromisoformat(week_start)
    for i, pnl in enumerate(pnls):
        exit_time = (base + timedelta(hours=i)).isoformat()
        conn.execute(
            """
            INSERT INTO paper_trades
            (trade_id, symbol, side, quantity, entry_price, exit_price, entry_time, exit_time, pnl, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"trade{i}", symbol, "buy", 1.0, 100.0, 100.0, exit_time, exit_time, pnl, "closed"),
        )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# 1. Sharpe ratio — three call sites
# ---------------------------------------------------------------------------


class TestSharpeConsistency:
    """backtest/metrics.py (canonical) vs agents/strategy_metrics.py (should
    reuse the canonical formula) vs routers/wfe_router.py (independent,
    known-divergent implementation as of 2026-07-15)."""

    def test_strategy_metrics_reuses_canonical_sharpe_exactly(self):
        """compute_recent_risk_metrics() explicitly claims (per its own
        docstring) to reuse `backtest.metrics.calculate_metrics` rather than
        reimplementing Sharpe. Verify that claim numerically: build the same
        10-trade fixture two ways (once as a BacktestResult, once as the
        list-of-dicts shape compute_recent_risk_metrics expects) and confirm
        bit-for-bit agreement."""
        canonical = _make_backtest_result(PNLS)

        closed_trades = [{"pnl": p} for p in PNLS]
        risk_metrics = compute_recent_risk_metrics(closed_trades, INITIAL_CAPITAL)

        assert risk_metrics is not None, "expected >=10 trades to clear MIN_TRADES_FOR_RISK_METRICS"
        assert risk_metrics["sharpe_ratio"] == pytest.approx(canonical.sharpe_ratio, rel=1e-12)
        assert risk_metrics["sortino_ratio"] == pytest.approx(canonical.sortino_ratio, rel=1e-12)
        assert risk_metrics["win_rate"] == pytest.approx(canonical.win_rate, rel=1e-12)
        assert risk_metrics["profit_factor"] == pytest.approx(canonical.profit_factor, rel=1e-12)

    def test_wfe_router_sharpe_matches_canonical(self):
        """LIVE FINDING, caught while building this harness: at the moment
        this suite was first drafted (2026-07-15), `_compute_snapshot_stats()`
        computed Sharpe as a bare, un-annualized `mean(pnl) / stdev(pnl)` in
        raw dollars — a genuine, silent divergence from
        `backtest.metrics.compute_sharpe_sortino()`'s canonical per-trade,
        sqrt(252)-annualized formula (same metric name, different number:
        0.3914 vs. 6.2132 on this fixture, a ~15.87x = sqrt(252) gap).

        A concurrent process fixed this (the "D1" fix the task brief
        anticipated might land mid-session) WHILE this test file was being
        written — confirmed via `git diff engine/routers/wfe_router.py`,
        which shows the inline `statistics.mean/stdev` block replaced with a
        call into `backtest.metrics.compute_sharpe_sortino()` via a minimal
        BacktestResult, the same reuse pattern
        `agents/strategy_metrics.py::compute_recent_risk_metrics()` already
        used. This test now asserts the FIXED behavior and acts as the
        regression guard against a future reimplementation drifting again.
        Tolerance is `abs=1e-4` because the router rounds its output to 4
        decimal places before returning it.
        """
        canonical = _make_backtest_result(PNLS)

        week_start = "2026-07-13"
        conn = _make_paper_trades_db(PNLS, "TESTX", week_start)
        try:
            stats = _compute_snapshot_stats("TESTX", week_start, conn)
        finally:
            conn.close()

        assert stats["sharpe"] == pytest.approx(canonical.sharpe_ratio, abs=1e-4)


# ---------------------------------------------------------------------------
# 2. VaR / CVaR — single-sample percentile vs bootstrap-resampled
# ---------------------------------------------------------------------------


class TestVarCvarConsistency:
    """backtest/metrics.py's var_95/cvar_95 (single-sample percentile, stored
    as a FRACTION of initial_capital) vs backtest/monte_carlo.py's
    compute_var()/compute_cvar() (bootstrap-resampled, stored in raw USD
    dollars per that module's own docstring). These are DIFFERENT
    statistical methods answering related-but-distinct questions:
      - metrics.py: "what loss level did the 5th-worst-percentile trade in
        THIS OBSERVED sample actually hit?" (point estimate only)
      - monte_carlo.py: "if we resampled this trade-generating process many
        times, what's the distribution of that same percentile estimate?"
        (median + 95% CI, plus a point estimate using the same percentile
        formula as metrics.py on the *observed* sample before resampling)

    Reading both implementations shows the *point estimates* are actually
    the same np.percentile(...) formula applied to the same data, differing
    only by the known initial_capital scale factor -- so those two should
    match almost exactly. The bootstrap median/CI, by contrast, is a
    genuinely different quantity and is checked with a tolerance band, not
    equality.
    """

    def test_var_cvar_point_estimates_match_after_unit_conversion(self):
        """metrics.py stores var_95/cvar_95 as fractions of initial_capital;
        monte_carlo.py's point estimate ('var_pct'/'cvar') is in raw dollars.
        np.percentile is linear under positive scaling, so
        metrics_fraction * initial_capital should equal the monte_carlo
        dollar point estimate to floating-point precision -- NOT just
        approximately, because it is literally the same percentile
        computation on rescaled data.
        """
        canonical = _make_backtest_result(PNLS)
        assert canonical.total_trades >= 10  # var_95/cvar_95 only computed for n>=10

        var_result = compute_var(PNLS, confidence=0.95, n_resamples=2000, seed=42)
        cvar_result = compute_cvar(PNLS, confidence=0.95, n_resamples=2000, seed=42)

        assert canonical.var_95 * INITIAL_CAPITAL == pytest.approx(var_result["var_pct"], rel=1e-9)
        assert canonical.cvar_95 * INITIAL_CAPITAL == pytest.approx(cvar_result["cvar"], rel=1e-9)

    def test_var_cvar_bootstrap_distribution_is_close_not_equal(self):
        """The bootstrap median/CI is a genuinely different statistic from
        the observed-sample point estimate (small-n resampling has real
        sampling variance/bias, especially at n=10 trades). This test does
        NOT assert equality -- it asserts the documented, expected
        relationship: the deterministic point estimate must fall inside its
        own bootstrap 95% CI (a sanity check that the resampling procedure
        isn't producing a nonsensical/inverted band), and the bootstrap
        median must be within a generous tolerance band of the point
        estimate rather than wildly divergent.
        """
        var_result = compute_var(PNLS, confidence=0.95, n_resamples=5000, seed=42)
        cvar_result = compute_cvar(PNLS, confidence=0.95, n_resamples=5000, seed=42)

        # Point estimate must sit within the bootstrap CI band.
        assert var_result["var_ci_95_low"] <= var_result["var_pct"] <= var_result["var_ci_95_high"]
        assert cvar_result["cvar_ci_95_low"] <= cvar_result["cvar"] <= cvar_result["cvar_ci_95_high"]

        # "Close, not equal": bootstrap median within a generous band of the
        # point estimate. Band is wide on purpose (small-n bootstrap bias is
        # real) -- this is a sanity check against a broken resampler, not a
        # precision assertion.
        assert var_result["median_var"] == pytest.approx(var_result["var_pct"], abs=40.0)
        assert cvar_result["median_cvar"] == pytest.approx(cvar_result["cvar"], abs=40.0)


# ---------------------------------------------------------------------------
# 3. Black-76 pricing primitives — premium_calculator.py vs greeks_monitor.py
# ---------------------------------------------------------------------------


class TestBlack76CrossModuleIdentity:
    """Both options/premium_calculator.py and options/greeks_monitor.py
    independently define `_d1_d2` / `_norm_cdf` / `_norm_pdf` (confirmed by
    reading both files: identical math, duplicated, not shared via import).
    `greeks_monitor.calculate_greeks()` does import `black76_price` from
    premium_calculator for its rho leg, but delta/gamma/theta/vega are all
    computed from greeks_monitor's OWN _d1_d2/_norm_cdf/_norm_pdf. If those
    duplicated primitives ever drift from premium_calculator's, delta/gamma
    would silently disagree with the price/rho computed via the shared
    function. These should be EXACT duplicates -- any difference here is a
    real bug, not a modeling choice.
    """

    CASES = [
        # (F, K, T, r, sigma) -- MES/MGC-like futures-options parameter sets
        (5000.0, 5000.0, 30 / 365, 0.05, 0.20),  # ATM
        (2400.0, 2350.0, 45 / 365, 0.045, 0.18),  # slightly ITM call / OTM put
        (75.0, 80.0, 14 / 365, 0.05, 0.35),  # OTM call / ITM put, short-dated
    ]

    @pytest.mark.parametrize("F,K,T,r,sigma", CASES)
    def test_d1_d2_bit_identical_across_modules(self, F, K, T, r, sigma):
        d1_pc, d2_pc = pc._d1_d2(F, K, T, sigma)
        d1_gm, d2_gm = gm._d1_d2(F, K, T, sigma)
        assert d1_pc == pytest.approx(d1_gm, abs=1e-12)
        assert d2_pc == pytest.approx(d2_gm, abs=1e-12)

    @pytest.mark.parametrize("x", [-2.5, -1.0, -0.1, 0.0, 0.1, 1.0, 2.5])
    def test_norm_cdf_and_pdf_bit_identical_across_modules(self, x):
        assert pc._norm_cdf(x) == pytest.approx(gm._norm_cdf(x), abs=1e-14)
        assert pc._norm_pdf(x) == pytest.approx(gm._norm_pdf(x), abs=1e-14)

    @pytest.mark.parametrize("F,K,T,r,sigma", CASES)
    @pytest.mark.parametrize("option_type", ["call", "put"])
    def test_price_reconstructed_from_greeks_module_matches_premium_calculator(
        self, F, K, T, r, sigma, option_type
    ):
        """Manually re-derive the Black-76 price using ONLY greeks_monitor's
        private primitives (the same formula premium_calculator.black76_price
        uses internally) and confirm it matches premium_calculator's actual
        production output. This is the concrete "same (F,K,T,r,sigma) through
        both modules' independent code paths" check the gap analysis asked
        for -- proving the two duplicated implementations haven't drifted.
        """
        d1, d2 = gm._d1_d2(F, K, T, sigma)
        disc = math.exp(-r * T)
        if option_type == "call":
            raw_price_via_gm = disc * (F * gm._norm_cdf(d1) - K * gm._norm_cdf(d2))
        else:
            raw_price_via_gm = disc * (K * gm._norm_cdf(-d2) - F * gm._norm_cdf(-d1))

        production_price = pc.black76_price(F, K, T, r, sigma, option_type)

        # production_price is round(price, 4) -- compare at that precision.
        assert production_price == pytest.approx(raw_price_via_gm, abs=1e-4)


# ---------------------------------------------------------------------------
# 4. Win rate — computed independently in three places
# ---------------------------------------------------------------------------


class TestWinRateConsistency:
    def test_win_rate_agrees_across_metrics_strategy_metrics_and_wfe_router(self):
        canonical = _make_backtest_result(PNLS)

        closed_trades = [{"pnl": p} for p in PNLS]
        risk_metrics = compute_recent_risk_metrics(closed_trades, INITIAL_CAPITAL)

        week_start = "2026-07-13"
        conn = _make_paper_trades_db(PNLS, "TESTX", week_start)
        try:
            wfe_stats = _compute_snapshot_stats("TESTX", week_start, conn)
        finally:
            conn.close()

        assert canonical.win_rate == pytest.approx(0.5, abs=1e-12)
        assert risk_metrics["win_rate"] == pytest.approx(canonical.win_rate, rel=1e-12)
        assert wfe_stats["win_rate"] == pytest.approx(canonical.win_rate, rel=1e-12)


# ---------------------------------------------------------------------------
# 5. Kelly fraction — backtest/metrics.py vs risk/position_sizer.py vs
#    utils/position_sizing.py
# ---------------------------------------------------------------------------


class TestKellyFractionConsistency:
    """Three independent Kelly implementations:
      - backtest/metrics.py::compute_kelly_fraction(result) -- clamps raw
        Kelly to [0, 1], half_kelly_fraction = kelly_fraction / 2.0
      - risk/position_sizer.py::kelly_fraction(win_rate, avg_win, avg_loss)
        -- SAME raw formula, but clamps to [0, 0.25] ("quarter-Kelly... for
        safety", per its own docstring) -- a deliberate, documented policy
        difference, not a bug.
      - utils/position_sizing.py::calculate_half_kelly_size(...) -- SAME raw
        formula again, returns both the uncapped 'kelly_fraction' and
        'half_kelly' = kelly_fraction / 2.0 (the risk_pct field it also
        returns is separately capped at max_risk_pct, but half_kelly itself
        is not).

    All three implement literally the same textbook formula
    f* = (b*p - q) / b (b = payoff ratio, p = win_rate, q = 1-p). This suite
    verifies (a) the raw/uncapped formula agrees exactly across all three
    when no cap binds, (b) the half-Kelly relationship is exactly 0.5x
    between the two modules that expose it, and (c) documents -- without
    forcing a false equivalence -- that risk/position_sizer.py's 0.25 cap is
    a different, tighter policy ceiling than the other two, so its output is
    NOT directly comparable to "2x half-Kelly" once that cap is active.
    """

    def test_raw_formula_agrees_with_no_cap_binding(self):
        """win_rate=0.5, avg_win/avg_loss ratio=1.2 -> raw Kelly ~= 0.0833,
        comfortably under every module's cap (1.0, 0.25, and the implicit
        max_risk_pct=0.06 in calculate_half_kelly_size only caps risk_pct,
        not the returned kelly_fraction/half_kelly values)."""
        result = BacktestResult(
            symbol="TESTX",
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=INITIAL_CAPITAL,
            final_capital=INITIAL_CAPITAL,
            win_rate=0.5,
            avg_win=1.2,
            avg_loss=-1.0,  # metrics.py stores avg_loss as a signed (negative) number
        )
        compute_kelly_fraction(result)

        risk_raw = risk_kelly_fraction(win_rate=0.5, avg_win=1.2, avg_loss=1.0)  # positive per its own docstring
        half_kelly_result = calculate_half_kelly_size(
            capital=INITIAL_CAPITAL,
            win_rate=0.5,
            avg_win_loss_ratio=1.2,
            tick_value=5.0,
            atr_ticks=10.0,
        )

        expected_raw = (0.5 * 1.2 - 0.5) / 1.2  # 0.08333...
        assert result.kelly_fraction == pytest.approx(expected_raw, rel=1e-12)
        assert risk_raw == pytest.approx(expected_raw, rel=1e-12)
        assert half_kelly_result["kelly_fraction"] == pytest.approx(expected_raw, rel=1e-12)

    def test_half_kelly_relationship_is_exactly_0_5x(self):
        """Using the main 10-trade fixture (raw Kelly ~= 0.303, still under
        metrics.py's [0,1] clamp): confirm half_kelly_fraction is EXACTLY
        kelly_fraction/2 in both metrics.py and utils/position_sizing.py,
        and that the two modules' half-Kelly outputs agree with each other."""
        canonical = _make_backtest_result(PNLS)  # already runs compute_kelly_fraction via calculate_metrics

        expected_raw = (0.5 * (132.0 / 52.0) - 0.5) / (132.0 / 52.0)
        assert canonical.kelly_fraction == pytest.approx(expected_raw, rel=1e-9)
        assert canonical.half_kelly_fraction == pytest.approx(canonical.kelly_fraction / 2.0, rel=1e-12)

        half_kelly_result = calculate_half_kelly_size(
            capital=INITIAL_CAPITAL,
            win_rate=0.5,
            avg_win_loss_ratio=132.0 / 52.0,
            tick_value=5.0,
            atr_ticks=10.0,
        )
        assert half_kelly_result["kelly_fraction"] == pytest.approx(canonical.kelly_fraction, rel=1e-9)
        assert half_kelly_result["half_kelly"] == pytest.approx(half_kelly_result["kelly_fraction"] / 2.0, rel=1e-12)
        assert half_kelly_result["half_kelly"] == pytest.approx(canonical.half_kelly_fraction, rel=1e-9)

    def test_risk_position_sizer_cap_is_a_documented_policy_difference_not_a_bug(self):
        """GENUINE, DOCUMENTED DIVERGENCE (by design, per the module's own
        docstring -- flagged here so nobody assumes risk/position_sizer.py's
        kelly_fraction() is comparable to "2x half-Kelly" from the other two
        modules once the raw edge exceeds 0.25).

        On the main 10-trade fixture, raw Kelly ~= 0.303 (> 0.25). metrics.py
        clamps to [0, 1] (no effect here, still 0.303). risk/position_sizer's
        kelly_fraction() clamps to [0, 0.25] ("quarter-Kelly... for safety")
        and therefore returns exactly 0.25 here -- a different, tighter,
        deliberately-chosen safety ceiling, not the same "half of full-Kelly"
        semantics the other two modules share. This test does NOT assert
        risk_kelly == 2 * something (that would be a false equivalence); it
        asserts the cap value itself so a future refactor that silently
        changes 0.25 to some other number gets caught.
        """
        raw_kelly = (0.5 * (132.0 / 52.0) - 0.5) / (132.0 / 52.0)
        assert raw_kelly > 0.25  # confirms this fixture actually exercises the cap

        risk_capped = risk_kelly_fraction(win_rate=0.5, avg_win=132.0, avg_loss=52.0)
        assert risk_capped == pytest.approx(0.25, abs=1e-12)
        assert risk_capped != pytest.approx(raw_kelly, rel=1e-6)  # documents the cap actually binds here
