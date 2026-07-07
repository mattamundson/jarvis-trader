"""
Recurrence-prevention regression suite — 2026-06-02 false-drawdown incident.

Root cause: IB demo account DUP662235 (pre-seeded NAV ~$3.97M) contaminated
two daily_pnl rows (ending_balance=$31,507 and $113,482). get_peak_balance()
returned $113,482 vs current balance of $8,456 → drawdown = 92.6% → kill
switch would have fired on the next paper trade.

Three defensive layers now guard against recurrence:

  Layer 1 — Write guard (record_eod_snapshot):
      When state.source in ("memory", "ib") and paper tracker is wired,
      _read_memory() replaces the IB state, so ending_balance written to
      daily_pnl uses the paper tracker balance, not the IB NAV.

  Layer 2 — Read ceiling (get_peak_balance):
      Rows where ending_balance > starting_balance × PLAUSIBLE_PEAK_MULTIPLE (10×)
      are excluded from the peak calculation on every read.

  Layer 3 — Drawdown read-path (get_drawdown_pct):
      When source="memory", uses the paper tracker equity-curve peak (session
      scope only), not the all-time DB history peak.

Known limitation of Layer 2:
      The ceiling is 10× starting capital ($100k on a $10k book). The incident's
      $31,507 row (3.15×) is WITHIN the ceiling and would NOT be excluded. The
      write guard (Layer 1) is the primary recurrence prevention. Layer 2 catches
      only extreme contamination such as a direct IB NAV bleed ($3.97M = 397×).

MAX_DRAWDOWN_PCT discrepancy (documented intentionally):
      config.py default = 0.10 (10%).
      engine/.env runtime override = 0.20 (20%).
      Tests in test_safety_fixes_2026_06_01.py use 0.10 (the stricter value).
      This is a deliberate runtime relaxation for a $10k account ($200 max daily
      loss vs $100) — do not silently reduce without Tier 3 review.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from risk.pnl_monitor import PnLMonitor, PnLState

# engine/.env (the runtime override source) is gitignored and absent in CI,
# so the .env-presence guard below only executes where it actually exists.
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

# ── helpers ────────────────────────────────────────────────────────────────────


def _paper_perf(
    total_pnl: float = -150.0,
    starting_balance: float = 10_000.0,
    total_trades: int = 2,
    winning_trades: int = 1,
    losing_trades: int = 1,
) -> dict:
    current = starting_balance + total_pnl
    return {
        "total_pnl": total_pnl,
        "starting_balance": starting_balance,
        "equity_curve": [starting_balance, current],
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
    }


def _make_monitor(
    rows: list[dict] | None = None,
    paper_perf: dict | None = None,
    starting_balance: float = 10_000.0,
) -> PnLMonitor:
    db = MagicMock()
    if rows is not None:
        db.get_daily_pnl.return_value = rows
    paper = None
    if paper_perf is not None:
        paper = MagicMock()
        paper.get_performance.return_value = paper_perf
    return PnLMonitor(db_manager=db, paper_tracker=paper, starting_balance=starting_balance)


# ── Layer 1: Write Guard ───────────────────────────────────────────────────────


class TestLayer1WriteGuard:
    """record_eod_snapshot must use paper tracker balance when source='ib'."""

    def test_ib_nav_bleed_prevented(self):
        """
        The 2026-06-02 incident scenario: IB demo NAV $3.97M vs paper $9,850.
        ending_balance written to daily_pnl must be $9,850, not $3,970,000.
        """
        perf = _paper_perf(total_pnl=-150.0, starting_balance=10_000.0)
        monitor = _make_monitor(paper_perf=perf)
        monitor._cached_state = PnLState(
            current_balance=3_970_000.0,
            starting_balance=10_000.0,
            source="ib",
        )
        with patch.object(monitor, "get_drawdown_pct", return_value=-0.015):
            result = monitor.record_eod_snapshot()

        assert result is True
        ending = monitor._db.upsert_daily_pnl.call_args[1]["ending_balance"]
        assert ending < 100_000.0, (
            f"IB NAV bled into ending_balance={ending:.2f}. "
            "Write guard failed — this is the 2026-06-02 contamination pattern."
        )
        assert ending == pytest.approx(9_850.0, rel=0.01)

    def test_memory_source_also_uses_paper_balance(self):
        """source='memory' path: same guarantee as source='ib'."""
        perf = _paper_perf(total_pnl=200.0, starting_balance=10_000.0)
        monitor = _make_monitor(paper_perf=perf)
        monitor._cached_state = PnLState(
            current_balance=10_200.0,
            starting_balance=10_000.0,
            source="memory",
        )
        with patch.object(monitor, "get_drawdown_pct", return_value=0.0):
            monitor.record_eod_snapshot()

        ending = monitor._db.upsert_daily_pnl.call_args[1]["ending_balance"]
        assert ending == pytest.approx(10_200.0, rel=0.01)

    def test_no_paper_tracker_uses_ib_state(self):
        """No paper tracker wired → IB state is written (existing behaviour)."""
        monitor = _make_monitor(paper_perf=None)
        monitor._cached_state = PnLState(
            current_balance=10_050.0,
            starting_balance=10_000.0,
            source="ib",
        )
        with patch.object(monitor, "get_drawdown_pct", return_value=0.0):
            monitor.record_eod_snapshot()

        ending = monitor._db.upsert_daily_pnl.call_args[1]["ending_balance"]
        assert ending == pytest.approx(10_050.0, rel=0.01)

    def test_paper_read_failure_falls_back_gracefully(self):
        """_read_memory error → IB state used as fallback, no crash."""
        paper = MagicMock()
        paper.get_performance.side_effect = RuntimeError("tracker down")
        monitor = PnLMonitor(
            db_manager=MagicMock(), paper_tracker=paper, starting_balance=10_000.0
        )
        monitor._cached_state = PnLState(
            current_balance=9_900.0,
            starting_balance=10_000.0,
            source="ib",
        )
        with patch.object(monitor, "get_drawdown_pct", return_value=-0.01):
            result = monitor.record_eod_snapshot()

        assert result is True

    def test_starting_balance_written_is_paper_starting(self):
        """starting_balance in the DB row must also reflect paper, not IB."""
        perf = _paper_perf(total_pnl=-50.0, starting_balance=10_000.0)
        monitor = _make_monitor(paper_perf=perf)
        monitor._cached_state = PnLState(
            current_balance=3_970_000.0,
            starting_balance=3_970_000.0,
            source="ib",
        )
        with patch.object(monitor, "get_drawdown_pct", return_value=-0.005):
            monitor.record_eod_snapshot()

        kwargs = monitor._db.upsert_daily_pnl.call_args[1]
        assert kwargs["starting_balance"] < 100_000.0, (
            "IB demo starting_balance leaked into daily_pnl row"
        )


# ── Layer 2: Read-Path Ceiling ─────────────────────────────────────────────────


class TestLayer2ReadCeiling:
    """get_peak_balance() ceiling blocks extreme contaminated rows on the read path."""

    def test_plausible_peak_multiple_is_5(self):
        """
        PLAUSIBLE_PEAK_MULTIPLE must stay at 5.0.

        5× = $50k ceiling on a $10k paper book. Any single-day gain above
        500% is not a real forward-validation result. Reducing it below 3×
        could flag legitimate equity peaks; increasing it lets more
        contaminated rows through. Any change requires a deliberate Tier 3
        decision and must update this test to pin the new value.
        """
        monitor = _make_monitor(starting_balance=10_000.0)
        assert monitor.PLAUSIBLE_PEAK_MULTIPLE == 5.0, (
            "PLAUSIBLE_PEAK_MULTIPLE changed from 5.0. Verify the new value "
            "is safe before landing — see comment block in pnl_monitor.py."
        )

    def test_row_above_5x_ceiling_excluded(self):
        """$113,482 on a $10k book (11.35×) is excluded from peak (above 5× = $50k)."""
        rows = [
            {"ending_balance": 10_000.0},
            {"ending_balance": 10_330.0},
            {"ending_balance": 113_482.89},
        ]
        monitor = _make_monitor(rows=rows, starting_balance=10_000.0)
        peak = monitor.get_peak_balance()
        assert peak < 113_000.0, (
            f"11.35× row not excluded: peak={peak:.2f}. Ceiling guard failed."
        )
        assert peak == pytest.approx(10_330.0, rel=0.01)

    def test_direct_ib_nav_excluded(self):
        """$3.97M on a $10k book (397×) is excluded — the actual IB demo NAV."""
        rows = [
            {"ending_balance": 10_000.0},
            {"ending_balance": 10_330.0},
            {"ending_balance": 3_970_000.0},
        ]
        monitor = _make_monitor(rows=rows, starting_balance=10_000.0)
        peak = monitor.get_peak_balance()
        assert peak == pytest.approx(10_330.0, rel=0.01), (
            f"$3.97M IB NAV not excluded from peak: got {peak:.2f}"
        )

    def test_mid_range_contamination_is_not_caught_by_ceiling(self):
        """
        DOCUMENTED LIMITATION: the $31,507 incident row (3.15×) falls within
        the 5× ceiling ($50k) and is kept. The write guard (Layer 1) is the
        primary defense against mid-range contamination; the ceiling only catches
        extreme contamination (above 5×). Catching this case via the ceiling
        would require lowering the multiple below 3.15, risking false-positives
        on legitimate early gains.

        If this test fails because the constant was tightened below 3.15, update
        the PLAUSIBLE_PEAK_MULTIPLE assertion in test_plausible_peak_multiple_is_5.
        """
        ceiling_5x = 10_000.0 * 5.0  # $50,000
        incident_row = 31_507.50
        assert incident_row < ceiling_5x, (
            "Test precondition: incident row is within the 5× ceiling. "
            f"{incident_row} < {ceiling_5x}"
        )
        rows = [
            {"ending_balance": 10_000.0},
            {"ending_balance": incident_row},
        ]
        monitor = _make_monitor(rows=rows, starting_balance=10_000.0)
        peak = monitor.get_peak_balance()
        assert peak == pytest.approx(incident_row, rel=0.01), (
            "Mid-range contamination kept (expected). "
            "If the ceiling was tightened, delete this test and update Layer 2 constants."
        )

    def test_clean_history_ceiling_has_no_effect(self):
        """Normal equity growth within ceiling — true max is returned."""
        rows = [{"ending_balance": v} for v in [10_000.0, 10_500.0, 11_200.0]]
        monitor = _make_monitor(rows=rows, starting_balance=10_000.0)
        assert monitor.get_peak_balance() == pytest.approx(11_200.0)


# ── Layer 3: End-to-End Kill Switch Safety ─────────────────────────────────────


class TestLayer3EndToEnd:
    """Full stack: contaminated daily_pnl → get_drawdown_pct → kill switch status."""

    def test_extreme_contamination_no_false_breach(self):
        """
        $3.97M direct IB NAV row: Layer 2 ceiling excludes it.
        Real balance $8,456 vs clean peak $10,330 = -18.1% drawdown.
        Below the 20% runtime halt threshold → kill switch must NOT fire.
        """
        rows = [
            {"ending_balance": 10_000.0},
            {"ending_balance": 10_330.0},
            {"ending_balance": 3_970_000.0},
        ]
        monitor = _make_monitor(rows=rows, starting_balance=10_000.0)
        state = PnLState(current_balance=8_456.0, starting_balance=10_000.0, source="sqlite")
        with patch.object(monitor, "get_current_pnl_state", return_value=state):
            dd = monitor.get_drawdown_pct()

        assert dd > -0.20, (
            f"False breach: drawdown={dd:.4f} with $3.97M contamination excluded by ceiling. "
            "Layer 2 ceiling guard failed to protect the kill switch."
        )
        expected = (8_456.0 - 10_330.0) / 10_330.0
        assert dd == pytest.approx(expected, rel=0.01)

    def test_no_history_no_drawdown(self):
        """Empty daily_pnl table → peak = 0 → drawdown = 0.0 (safe default)."""
        monitor = _make_monitor(rows=[], starting_balance=10_000.0)
        state = PnLState(current_balance=9_500.0, starting_balance=10_000.0, source="sqlite")
        with patch.object(monitor, "get_current_pnl_state", return_value=state):
            dd = monitor.get_drawdown_pct()
        assert dd == pytest.approx(0.0)

    def test_memory_source_uses_tracker_peak_not_db(self):
        """
        source='memory': drawdown uses paper tracker equity-curve peak (session),
        not the all-time DB history. An old DB peak cannot inflate the drawdown.
        """
        perf = _paper_perf(total_pnl=-100.0, starting_balance=10_000.0)
        rows = [{"ending_balance": 50_000.0}]
        monitor = _make_monitor(rows=rows, paper_perf=perf)
        state = PnLState(current_balance=9_900.0, starting_balance=10_000.0, source="memory")
        with patch.object(monitor, "get_current_pnl_state", return_value=state):
            dd = monitor.get_drawdown_pct()

        expected = (9_900.0 - 10_000.0) / 10_000.0
        assert dd == pytest.approx(expected, rel=0.01), (
            f"source='memory' path should use paper peak ($10k), not DB peak ($50k). "
            f"Got dd={dd:.4f}, expected ~{expected:.4f}"
        )

    def test_should_halt_returns_false_below_20pct_runtime_threshold(self):
        """
        Drawdown of -18.1% (current post-incident state) is below the 20%
        runtime threshold from engine/.env — should_halt_trading returns False.
        """
        rows = [
            {"ending_balance": 10_330.0},
            {"ending_balance": 3_970_000.0},
        ]
        monitor = _make_monitor(rows=rows, starting_balance=10_000.0)
        state = PnLState(
            current_balance=8_456.0,
            daily_realized_pnl=-120.0,
            daily_unrealized_pnl=0.0,
            starting_balance=10_000.0,
            source="sqlite",
        )
        with patch.object(monitor, "get_current_pnl_state", return_value=state):
            halt, reason = monitor.should_halt_trading(
                daily_loss_limit_pct=-0.02,
                drawdown_limit_pct=-0.20,
            )

        assert halt is False, (
            f"False halt triggered at -18.1% drawdown with 20% limit. reason={reason}"
        )


# ── MAX_DRAWDOWN_PCT Discrepancy Documentation ─────────────────────────────────


class TestMaxDrawdownPctDiscrepancy:
    """
    Documents the intentional discrepancy between config.py default and
    the engine/.env runtime override. Tests here pin the KNOWN values.

    If either value changes, this test fails as a mandatory review gate.
    """

    @pytest.mark.skipif(
        not _ENV_FILE.exists(),
        reason="guards the engine/.env runtime override (0.20); .env is gitignored/absent in CI",
    )
    def test_runtime_max_drawdown_is_20pct(self):
        """
        The runtime MAX_DRAWDOWN_PCT is 0.20 (20%), loaded from engine/.env.

        docs/safety.md states 10% — that is the CODE DEFAULT in config.py source.
        The engine/.env intentionally overrides to 20% for a $10k account
        (stricter: $200 max daily loss; docs/safety.md is stale on this value).

        If this assertion fails, someone changed engine/.env without a Tier 3
        review. Update docs/safety.md if the change is intentional.
        """
        from config import TradingConfig
        cfg = TradingConfig()
        assert cfg.MAX_DRAWDOWN_PCT == pytest.approx(0.20), (
            f"MAX_DRAWDOWN_PCT = {cfg.MAX_DRAWDOWN_PCT} — expected 0.20 (from engine/.env). "
            "If changed intentionally, update docs/safety.md and this test. Tier 3 required."
        )

    def test_should_halt_uses_drawdown_limit_parameter(self):
        """
        should_halt_trading accepts drawdown_limit_pct as a parameter, letting
        callers pass the .env-overridden value (0.20) rather than 0.10.
        At -19% drawdown: fires with 10% limit, silent with 20% limit.
        """
        rows = [{"ending_balance": 10_000.0}]
        monitor = _make_monitor(rows=rows, starting_balance=10_000.0)
        state = PnLState(
            current_balance=8_100.0,
            daily_realized_pnl=-100.0,
            daily_unrealized_pnl=0.0,
            starting_balance=10_000.0,
            source="sqlite",
        )
        with patch.object(monitor, "get_current_pnl_state", return_value=state):
            halt_strict, reason_strict = monitor.should_halt_trading(
                daily_loss_limit_pct=-0.02,
                drawdown_limit_pct=-0.10,
            )
            halt_relaxed, _ = monitor.should_halt_trading(
                daily_loss_limit_pct=-0.02,
                drawdown_limit_pct=-0.20,
            )

        assert halt_strict is True, (
            f"At -19% drawdown with 10% limit, halt must fire. reason={reason_strict}"
        )
        assert halt_relaxed is False, (
            "At -19% drawdown with 20% limit, halt must NOT fire"
        )


# ── Layer 2b: trailing-window high-water mark ────────────────────────────────────


class _WindowDb:
    """Fake db whose get_daily_pnl honors the days= cutoff like the real mixin
    (rows with date >= today-UTC - days). Lets us prove the temporal guard
    end-to-end rather than against an arg-ignoring MagicMock."""

    def __init__(self, rows):
        self._rows = rows

    def get_daily_pnl(self, days=None, start_date=None, end_date=None):
        if days is None:
            return list(self._rows)
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).date().isoformat()
        return [r for r in self._rows if str(r.get("date", "")) >= cutoff]


class _NoDaysDb:
    """Fake db that predates the days= cutoff: raises TypeError if days is passed."""

    def __init__(self, rows):
        self._rows = rows

    def get_daily_pnl(self, *args, **kwargs):
        if "days" in kwargs:
            raise TypeError("get_daily_pnl() got an unexpected keyword argument 'days'")
        return list(self._rows)


class TestLayer2bTrailingWindow:
    """A plausible-but-STALE high row must not set the peak (it would mask a real
    current drawdown). 90-day trailing window excludes it."""

    def _rows_fresh_plus_stale(self):
        from datetime import date, timedelta
        today = date.today().isoformat()
        stale = (date.today() - timedelta(days=120)).isoformat()
        # Both rows are WITHIN the 5x plausibility ceiling ($50k on a $10k book),
        # so only the temporal window can exclude the stale one.
        return [
            {"date": stale, "ending_balance": 11_800.0},  # months-old peak
            {"date": today, "ending_balance": 11_200.0},  # current
        ]

    def test_stale_high_row_excluded_by_window(self):
        rows = self._rows_fresh_plus_stale()
        monitor = PnLMonitor(
            db_manager=_WindowDb(rows), paper_tracker=None, starting_balance=10_000.0
        )
        # Window applied: stale $11,800 dropped -> peak is the current $11,200.
        assert monitor.get_peak_balance() == pytest.approx(11_200.0)

    def test_scenario_is_real_without_window(self):
        # Sanity: unbounded read would pick the stale $11,800 (the masking bug).
        rows = self._rows_fresh_plus_stale()
        assert max(r["ending_balance"] for r in rows) == pytest.approx(11_800.0)

    def test_requests_trailing_window(self):
        db = MagicMock()
        db.get_daily_pnl.return_value = [{"date": "2026-06-12", "ending_balance": 11_000.0}]
        monitor = PnLMonitor(db_manager=db, paper_tracker=None, starting_balance=10_000.0)
        monitor.get_peak_balance()
        db.get_daily_pnl.assert_called_once_with(days=PnLMonitor.PEAK_LOOKBACK_DAYS)

    def test_falls_back_when_days_unsupported(self):
        rows = [{"date": "2026-06-12", "ending_balance": 11_000.0}]
        monitor = PnLMonitor(
            db_manager=_NoDaysDb(rows), paper_tracker=None, starting_balance=10_000.0
        )
        # TypeError on days= must fall back to the unbounded read, not crash.
        assert monitor.get_peak_balance() == pytest.approx(11_000.0)
