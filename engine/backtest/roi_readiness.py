#!/usr/bin/env python
"""
ROI Readiness Evaluator — $250/day × 14-trading-day Live-Trading Trigger

Purpose-built companion to live_readiness.py. While live_readiness.py checks
infrastructure/deployment gates (C1-C7), this module checks the performance-
based ROI trigger gates: is paper trading profitable enough and stable enough
to authorize real capital?

The 7 hard gates (G1-G7) must ALL hold for 14 consecutive trading days.
A single failure on any gate resets the consecutive-pass streak to 0.

Gate definitions:

    G1 — Paper PnL ≥ $250/day average
        Avg daily PnL over the last 14 trading days (M-F only, from pnl_snapshots
        table or paper_trades.json) must be ≥ $250. Uses the realistic cost tier.

        NOTE (v1 limitation): "trading days" = Monday-Friday calendar days.
        US market holidays are NOT excluded. This slightly overstates the trading-
        day count (~10 holidays/year → ~4% over-count per 14-day window). Acceptable
        for a milestone tracker; upgrade to a proper holiday calendar when needed.

    G2 — Win rate ≥ 35%
        Over the same 14-day window, at least 35% of closed round-trips must be
        winners (pnl > 0).

    G3 — Max single-day drawdown ≤ 5% of account
        No single day in the 14-day window had a peak-to-trough intraday equity
        loss > 5% of the portfolio_equity reading for that day. Reads from
        pnl_snapshots; falls back to per-day PnL / equity estimate.

    G4 — Max consecutive loss days ≤ 3
        The longest run of consecutive loss days (daily_pnl < 0) within the
        14-day window must be ≤ 3.

    G5 — Zero trades on DO_NOT_TRADE_SYMBOLS
        The paper_trades.json must contain no filled orders for any symbol in
        DO_NOT_TRADE_SYMBOLS over the 14-day window. Reads the runtime constant
        from backtest.signals — not hardcoded.

    G6 — Engine /health ≥ 95% of trading hours
        The pnl_snapshots table must have entries for ≥ 95% of the expected
        trading days in the 14-day window (proxy: if we have a snapshot for a
        day, the engine was healthy that day). Falls back to a live /health
        check for today.

    G7 — Each live strategy has gate v2 PASS verdict ≤ 30 days old
        Checks MES_trend_rank11.json and MGC_trend_rank4.json in
        engine/data/gate_v2_verdicts/. Both must have verdict=PASS and
        created_at within 30 days of the evaluation date.

Output:
    ROIReadinessResult dataclass with:
      - status: "GREEN" | "YELLOW" | "RED"
      - gates: list[GateResult]
      - pass_count: int (out of 7)
      - consecutive_passing_days: int (streak of days all 7 gates pass)
      - days_to_live: int (max(0, 14 - streak))
      - snapshot_date: date evaluated

Usage (from engine/ directory):
    .venv/Scripts/python -m backtest.roi_readiness
    .venv/Scripts/python -m backtest.roi_readiness --json
    .venv/Scripts/python -m backtest.roi_readiness --date 2026-05-07
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_ENGINE_ROOT = Path(__file__).parent.parent
_DB_PATH = _ENGINE_ROOT / "data" / "jarvis_trader.db"
_PAPER_TRADES_JSON = _ENGINE_ROOT / "data" / "paper_trades.json"
_VERDICTS_DIR = _ENGINE_ROOT / "data" / "gate_v2_verdicts"
_ENGINE_HEALTH_URL = "http://127.0.0.1:8010/health"
_ENGINE_TIMEOUT_SEC = 5

# Thresholds
WINDOW_TRADING_DAYS = 14          # G1-G6 evaluation window
DAILY_PNL_TARGET = 250.0          # G1: ≥ $250/day avg
WIN_RATE_MIN = 0.35               # G2: ≥ 35%
MAX_SINGLE_DAY_DD_PCT = 5.0       # G3: ≤ 5% of account
MAX_CONSEC_LOSS_DAYS = 3          # G4: ≤ 3 consecutive loss days
ENGINE_UPTIME_MIN_PCT = 95.0      # G6: ≥ 95% of polled trading-hours samples reachable
# health_watchdog polls every 5 min during the 6.5h RTH session ≈ 78 polls/day.
# Used to judge whether health_snapshots has enough samples to assert uptime.
_RTH_POLLS_PER_DAY = 78
VERDICT_TTL_DAYS = 30             # G7: verdict age limit
STREAK_TARGET = 14                # days_to_live = max(0, target - streak)

# Live strategies checked by G7
_LIVE_STRATEGY_VERDICTS: list[str] = [
    "MES_trend_rank11.json",
    "MGC_trend_rank4.json",
]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    gate_id: str           # "G1" – "G7"
    name: str
    passed: bool
    observed: str          # human-readable observed value
    threshold: str         # human-readable threshold
    notes: str = ""


@dataclass
class ROIReadinessResult:
    snapshot_date: date
    status: str                            # GREEN / YELLOW / RED
    pass_count: int
    gates: list[GateResult] = field(default_factory=list)
    consecutive_passing_days: int = 0
    days_to_live: int = STREAK_TARGET


# ---------------------------------------------------------------------------
# Helper: business-day window
# ---------------------------------------------------------------------------


def _trading_days_window(as_of: date, n: int = WINDOW_TRADING_DAYS) -> list[date]:
    """
    Return a list of up to `n` weekdays (Mon-Fri) ending on `as_of`, inclusive.

    v1 caveat: US market holidays are not excluded (see module docstring).
    """
    days: list[date] = []
    d = as_of
    while len(days) < n:
        if d.weekday() < 5:  # Mon=0 … Fri=4
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))  # chronological order


# ---------------------------------------------------------------------------
# Helper: load pnl_snapshots from DB
# ---------------------------------------------------------------------------


def _load_pnl_snapshots(days: list[date]) -> dict[date, dict[str, Any]]:
    """
    Return a dict {date: {daily_pnl, portfolio_equity, peak_equity, consecutive_losses}}
    for each day in `days` that has a pnl_snapshots row.
    """
    result: dict[date, dict[str, Any]] = {}
    if not _DB_PATH.exists():
        return result
    try:
        con = sqlite3.connect(str(_DB_PATH))
        placeholders = ",".join("?" * len(days))
        date_strs = [d.isoformat() for d in days]
        cur = con.execute(
            f"""
            SELECT date, daily_pnl, portfolio_equity, peak_equity, consecutive_losses
            FROM pnl_snapshots
            WHERE date IN ({placeholders})
            ORDER BY date
            """,
            date_strs,
        )
        for row in cur.fetchall():
            d = date.fromisoformat(row[0])
            result[d] = {
                "daily_pnl": row[1],
                "portfolio_equity": row[2],
                "peak_equity": row[3],
                "consecutive_losses": row[4],
            }
        con.close()
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Helper: load paper_trades.json for a date window
# ---------------------------------------------------------------------------


def _load_paper_trades_window(days: list[date]) -> list[dict]:
    """
    Return all paper trade entries whose timestamp falls on one of `days` (UTC date).
    """
    if not _PAPER_TRADES_JSON.exists():
        return []
    try:
        raw = json.loads(_PAPER_TRADES_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    trades_list: list[dict] = []
    if isinstance(raw, dict) and "trades" in raw:
        trades_list = raw["trades"]
    elif isinstance(raw, list):
        trades_list = raw

    day_set = {d.isoformat() for d in days}
    result = []
    for t in trades_list:
        ts_str = t.get("timestamp", "")
        if not ts_str:
            continue
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        # Use UTC date for simplicity (trades cluster around market hours)
        if dt.date().isoformat() in day_set:
            result.append(t)
    return result


# ---------------------------------------------------------------------------
# Helper: pair buy/sell into closed round-trips and compute per-day PnL
# ---------------------------------------------------------------------------

# NOTE: _INSTRUMENT_MULTIPLIERS is kept here only for backward compatibility
# with test code that patches it.  The canonical multipliers live in
# analytics.paper_trade_pairing.DEFAULT_MULTIPLIERS.
_INSTRUMENT_MULTIPLIERS: dict[str, float] = {
    "MES": 5.0,
    "MGC": 10.0,
    "MNQ": 2.0,
    "MCL": 100.0,
    "M2K": 5.0,
}


def _pair_trades_to_roundtrips(trades: list[dict]) -> list[dict]:
    """
    FIFO pairing of buy/sell sides into closed round-trips.

    Delegates to analytics.paper_trade_pairing.pair_trades which ALWAYS
    recomputes PnL from entry/exit prices × contract multiplier.

    IMPORTANT: the stored ``pnl`` field on sell entries in paper_trades.json
    is in price-point units (writer bug — multiplier was omitted).  Trusting
    that field caused G2 win_rate to read 0.0% even on profitable sessions.
    The shared helper ignores stored_pnl entirely.

    Returns list of dicts with keys: symbol, pnl, exit_date (date)
    """
    import sys
    from pathlib import Path

    # Ensure engine root is on path so the analytics package is importable
    _engine_root = Path(__file__).parent.parent
    if str(_engine_root) not in sys.path:
        sys.path.insert(0, str(_engine_root))

    from analytics.paper_trade_pairing import pair_trades as _pair_raw

    closed_rts = _pair_raw(trades)
    return [
        {
            "symbol": rt.symbol,
            "pnl": rt.pnl,
            "exit_date": rt.exit_time.date(),
        }
        for rt in closed_rts
    ]


# ---------------------------------------------------------------------------
# Helper: engine health check
# ---------------------------------------------------------------------------


def _fetch_engine_health() -> dict[str, Any] | None:
    """Best-effort engine /health fetch. Returns None on any error."""
    try:
        with urlopen(_ENGINE_HEALTH_URL, timeout=_ENGINE_TIMEOUT_SEC) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (URLError, HTTPError, json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Individual gate evaluators
# ---------------------------------------------------------------------------


def _eval_g1_daily_pnl(
    snapshots: dict[date, dict],
    roundtrips: list[dict],
    days: list[date],
) -> GateResult:
    """G1: avg daily PnL over last 14 trading days ≥ $250."""
    # Prefer pnl_snapshots (authoritative daily settlement), fallback to
    # summing roundtrips per day.
    daily_pnls: list[float] = []

    for d in days:
        if d in snapshots:
            daily_pnls.append(snapshots[d]["daily_pnl"])
        else:
            # Fallback: sum roundtrip PnL for that day
            day_pnl = sum(rt["pnl"] for rt in roundtrips if rt["exit_date"] == d)
            daily_pnls.append(day_pnl)

    if not daily_pnls:
        return GateResult(
            gate_id="G1",
            name="Paper PnL ≥ $250/day (14-day avg)",
            passed=False,
            observed="no data",
            threshold=f"≥ ${DAILY_PNL_TARGET:.0f}/day avg",
            notes="No pnl_snapshots rows and no paper trades in window",
        )

    avg_pnl = sum(daily_pnls) / len(daily_pnls)
    passed = avg_pnl >= DAILY_PNL_TARGET
    non_zero = sum(1 for x in daily_pnls if x != 0)

    return GateResult(
        gate_id="G1",
        name="Paper PnL ≥ $250/day (14-day avg)",
        passed=passed,
        observed=f"${avg_pnl:+.2f}/day avg ({len(daily_pnls)} days, {non_zero} active)",
        threshold=f"≥ ${DAILY_PNL_TARGET:.0f}/day avg",
        notes=(
            f"Daily PnLs: [{', '.join(f'${x:+.0f}' for x in daily_pnls[-5:])}] "
            "(last 5 shown)"
            if len(daily_pnls) > 5
            else f"Daily PnLs: {[f'${x:+.0f}' for x in daily_pnls]}"
        ),
    )


def _eval_g2_win_rate(roundtrips: list[dict]) -> GateResult:
    """G2: win rate ≥ 35% over 14-day window."""
    if not roundtrips:
        return GateResult(
            gate_id="G2",
            name="Win rate ≥ 35%",
            passed=False,
            observed="no closed trades",
            threshold=f"≥ {WIN_RATE_MIN * 100:.0f}%",
            notes="No closed round-trips in 14-day window",
        )

    wins = sum(1 for rt in roundtrips if rt["pnl"] > 0)
    total = len(roundtrips)
    wr = wins / total
    passed = wr >= WIN_RATE_MIN

    return GateResult(
        gate_id="G2",
        name="Win rate ≥ 35%",
        passed=passed,
        observed=f"{wr * 100:.1f}% ({wins}W / {total - wins}L of {total} trades)",
        threshold=f"≥ {WIN_RATE_MIN * 100:.0f}%",
    )


def _eval_g3_max_daily_drawdown(
    snapshots: dict[date, dict],
    roundtrips: list[dict],
    days: list[date],
) -> GateResult:
    """G3: max single-day drawdown ≤ 5% of account equity."""
    worst_dd_pct = 0.0
    worst_day: date | None = None

    for d in days:
        if d in snapshots:
            snap = snapshots[d]
            equity = snap["portfolio_equity"]
            peak = snap["peak_equity"]
            daily_pnl = snap["daily_pnl"]
            if equity and equity > 0 and daily_pnl < 0:
                # Approximate intraday drawdown as |daily_loss| / peak_equity
                # A proper intraday HWM would need tick data; this is a
                # conservative upper bound that's monotone in the right direction.
                dd_pct = abs(daily_pnl) / max(peak, equity) * 100.0
                if dd_pct > worst_dd_pct:
                    worst_dd_pct = dd_pct
                    worst_day = d

    if worst_day is None:
        # No drawdown days or no data
        return GateResult(
            gate_id="G3",
            name="Max single-day drawdown ≤ 5% of account",
            passed=True,
            observed="0.0% max dd (no loss days or no data)",
            threshold=f"≤ {MAX_SINGLE_DAY_DD_PCT:.0f}%",
            notes="Passed by absence: no loss days in window",
        )

    passed = worst_dd_pct <= MAX_SINGLE_DAY_DD_PCT
    return GateResult(
        gate_id="G3",
        name="Max single-day drawdown ≤ 5% of account",
        passed=passed,
        observed=f"{worst_dd_pct:.2f}% on {worst_day}",
        threshold=f"≤ {MAX_SINGLE_DAY_DD_PCT:.0f}%",
        notes=(
            "Drawdown approximated as |daily_loss| / peak_equity "
            "(intraday HWM not tracked at snapshot granularity)"
        ),
    )


def _eval_g4_consec_loss_days(
    snapshots: dict[date, dict],
    roundtrips: list[dict],
    days: list[date],
) -> GateResult:
    """G4: max consecutive loss days ≤ 3."""
    # Build a daily PnL series (same logic as G1)
    daily_pnls: list[tuple[date, float]] = []
    for d in days:
        if d in snapshots:
            daily_pnls.append((d, snapshots[d]["daily_pnl"]))
        else:
            day_pnl = sum(rt["pnl"] for rt in roundtrips if rt["exit_date"] == d)
            daily_pnls.append((d, day_pnl))

    # Find max run of consecutive loss days (pnl < 0)
    max_run = 0
    cur_run = 0
    worst_start: date | None = None
    cur_start: date | None = None

    for d, pnl in daily_pnls:
        if pnl < 0:
            cur_run += 1
            if cur_run == 1:
                cur_start = d
            if cur_run > max_run:
                max_run = cur_run
                worst_start = cur_start
        else:
            cur_run = 0
            cur_start = None

    passed = max_run <= MAX_CONSEC_LOSS_DAYS
    notes = f"Longest loss streak started {worst_start}" if worst_start else "No loss streaks"

    return GateResult(
        gate_id="G4",
        name="Max consecutive loss days ≤ 3",
        passed=passed,
        observed=f"{max_run} consecutive loss day(s)",
        threshold=f"≤ {MAX_CONSEC_LOSS_DAYS}",
        notes=notes,
    )


def _eval_g5_no_donottrade(
    paper_trades_window: list[dict],
) -> GateResult:
    """G5: zero filled orders on DO_NOT_TRADE_SYMBOLS in 14-day window."""
    try:
        from backtest.signals import DO_NOT_TRADE_SYMBOLS  # noqa: E402
    except ImportError:
        return GateResult(
            gate_id="G5",
            name="Zero trades on DO_NOT_TRADE_SYMBOLS",
            passed=False,
            observed="cannot import DO_NOT_TRADE_SYMBOLS",
            threshold="0 filled orders on blocked symbols",
            notes="Import error from backtest.signals — check engine path",
        )

    blocked_fills: list[str] = []
    for t in paper_trades_window:
        sym = t.get("symbol", "")
        side = (t.get("side") or "").lower()
        # Only count fills (has filled_price or trade_value), not open orders
        has_fill = t.get("filled_price") is not None or t.get("trade_value") is not None
        if sym in DO_NOT_TRADE_SYMBOLS and has_fill and side in ("buy", "sell"):
            blocked_fills.append(f"{sym}@{t.get('timestamp', '?')[:10]}")

    passed = len(blocked_fills) == 0
    return GateResult(
        gate_id="G5",
        name="Zero trades on DO_NOT_TRADE_SYMBOLS",
        passed=passed,
        observed=(
            f"{len(blocked_fills)} blocked fill(s): {blocked_fills[:5]}"
            if blocked_fills
            else f"0 fills (blocked set: {sorted(DO_NOT_TRADE_SYMBOLS)})"
        ),
        threshold="0 filled orders on blocked symbols",
        notes=f"Blocked symbols from backtest.signals: {sorted(DO_NOT_TRADE_SYMBOLS)}",
    )


def _eval_g6_engine_uptime(
    snapshots: dict[date, dict],
    days: list[date],
) -> GateResult:
    """
    G6: engine /health reachable ≥ 95% of polled trading-hours samples.

    Source of truth: scripts.health_uptime.compute_uptime() over the window,
    which reads the 5-minute health_snapshots table (health_watchdog polls every
    5 min during trading hours). The legacy day-level pnl_snapshots proxy (a row
    exists for the day ⇒ "healthy") is intentionally NOT used to PASS this gate:
    a snapshot row can exist for a day the engine was up only minutes, producing
    a false green. When the intraday data is too sparse to judge (health_snapshots
    not yet populated / pre-migration_025), the gate reports insufficient
    granularity and does NOT pass — readiness cannot be asserted on uptime that
    was never measured.

    `snapshots` (the day-level proxy data) is accepted for caller compatibility
    but deliberately not consulted for the pass/fail decision.
    """
    expected_days = len(days)
    if expected_days == 0:
        return GateResult(
            gate_id="G6",
            name="Engine /health ≥ 95% of trading hours",
            passed=False,
            observed="no trading days in window",
            threshold=f"≥ {ENGINE_UPTIME_MIN_PCT:.0f}%",
            notes="Empty evaluation window.",
        )

    # Query the real 5-min health_snapshots over the window. The watchdog only
    # writes rows during trading hours, so the full-day UTC range captures
    # exactly the RTH samples.
    up = {"polls_total": 0, "polls_reachable": 0, "uptime_pct": 0.0}
    try:
        from scripts.health_uptime import compute_uptime

        first, last = days[0], days[-1] + timedelta(days=1)
        window_start = datetime(first.year, first.month, first.day, tzinfo=timezone.utc)
        window_end = datetime(last.year, last.month, last.day, tzinfo=timezone.utc)
        up = compute_uptime(window_start, window_end)
    except (ImportError, sqlite3.Error, OSError, ValueError):
        # Degrade to insufficient-granularity below rather than a misleading pass.
        pass

    total_polls = up.get("polls_total", 0)
    reachable = up.get("polls_reachable", 0)

    # Require at least half the expected samples to trust the number; fewer means
    # the watchdog wasn't running (not that the engine was up) — the exact case
    # the old day-level proxy would have silently passed.
    min_sufficient = max(1, (_RTH_POLLS_PER_DAY * expected_days) // 2)
    if total_polls < min_sufficient:
        return GateResult(
            gate_id="G6",
            name="Engine /health ≥ 95% of trading hours",
            passed=False,
            observed=(
                f"insufficient granularity: {total_polls} health polls "
                f"(< {min_sufficient} needed over {expected_days} trading days)"
            ),
            threshold=f"≥ {ENGINE_UPTIME_MIN_PCT:.0f}%",
            notes=(
                "health_snapshots too sparse to verify intraday uptime; gate "
                "cannot PASS until the 5-min watchdog data accumulates "
                "(migration_025). Day-level pnl_snapshots presence is NOT used "
                "as a pass proxy — it false-greens on minutes-only uptime."
            ),
        )

    uptime_pct = (reachable / total_polls * 100.0) if total_polls > 0 else 0.0
    passed = uptime_pct >= ENGINE_UPTIME_MIN_PCT

    return GateResult(
        gate_id="G6",
        name="Engine /health ≥ 95% of trading hours",
        passed=passed,
        observed=f"{uptime_pct:.1f}% ({reachable}/{total_polls} health polls reachable)",
        threshold=f"≥ {ENGINE_UPTIME_MIN_PCT:.0f}%",
        notes="Intraday uptime from health_snapshots (5-min watchdog polls).",
    )


def _eval_g7_verdict_freshness(as_of: date) -> GateResult:
    """G7: MES_trend_rank11 and MGC_trend_rank4 both PASS and ≤ 30 days old."""
    now = datetime.combine(as_of, datetime.min.time()).replace(tzinfo=timezone.utc)
    results: list[str] = []
    failed: list[str] = []

    for fname in _LIVE_STRATEGY_VERDICTS:
        vpath = _VERDICTS_DIR / fname
        if not vpath.exists():
            failed.append(f"{fname}: file not found")
            continue
        try:
            v = json.loads(vpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            failed.append(f"{fname}: parse error ({e})")
            continue

        verdict = v.get("verdict", "?")
        created_at = v.get("created_at", "")
        if not created_at:
            failed.append(f"{fname}: missing created_at")
            continue

        try:
            created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            failed.append(f"{fname}: unparseable created_at={created_at!r}")
            continue

        age_days = (now - created_dt).days

        if verdict != "PASS":
            failed.append(f"{fname}: verdict={verdict} (not PASS)")
        elif age_days > VERDICT_TTL_DAYS:
            failed.append(f"{fname}: verdict PASS but {age_days}d old (limit {VERDICT_TTL_DAYS}d)")
        else:
            expiry = (created_dt + timedelta(days=VERDICT_TTL_DAYS)).date()
            results.append(f"{fname}: PASS ({age_days}d old, expires {expiry})")

    all_ok = len(failed) == 0
    return GateResult(
        gate_id="G7",
        name="Live strategy verdicts current (≤30d old)",
        passed=all_ok,
        observed=(
            "; ".join(results + [f"FAIL: {f}" for f in failed])
            if results or failed
            else "no verdicts checked"
        ),
        threshold=f"Both MES R11 + MGC R4 PASS, created_at ≤ {VERDICT_TTL_DAYS}d ago",
        notes=f"Checked: {', '.join(_LIVE_STRATEGY_VERDICTS)}",
    )


# ---------------------------------------------------------------------------
# Consecutive-streak counter
# ---------------------------------------------------------------------------


def compute_consecutive_passing_days(
    as_of: date,
    days: list[date],
    snapshots: dict[date, dict],
    roundtrips: list[dict],
    paper_trades_window: list[dict],
) -> int:
    """
    Walk backwards through `days` (newest first) and count how many consecutive
    days ALL 7 gates pass. Stops at the first failing day.

    For past days (not today) we skip G4/G6 live-health components and rely
    solely on snapshot data. G7 (verdict freshness) uses each day's date as
    the reference point so an old verdict can fail retroactively.
    """
    streak = 0
    for d in reversed(days):  # newest → oldest
        # Build a single-day window for this date
        single_day = [d]
        snap_single = {d: snapshots[d]} if d in snapshots else {}
        rt_single = [rt for rt in roundtrips if rt["exit_date"] == d]
        pt_single = [t for t in paper_trades_window if _trade_on_date(t, d)]

        gates_today = _run_all_gates(
            as_of=d,
            days=single_day,
            snapshots=snap_single,
            roundtrips=rt_single,
            paper_trades_window=pt_single,
        )
        if all(g.passed for g in gates_today):
            streak += 1
        else:
            break
    return streak


def _trade_on_date(t: dict, d: date) -> bool:
    ts_str = t.get("timestamp", "")
    if not ts_str:
        return False
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.date() == d
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Main evaluation entry point
# ---------------------------------------------------------------------------


def _run_all_gates(
    as_of: date,
    days: list[date],
    snapshots: dict[date, dict],
    roundtrips: list[dict],
    paper_trades_window: list[dict],
) -> list[GateResult]:
    """Run all 7 gates and return results."""
    return [
        _eval_g1_daily_pnl(snapshots, roundtrips, days),
        _eval_g2_win_rate(roundtrips),
        _eval_g3_max_daily_drawdown(snapshots, roundtrips, days),
        _eval_g4_consec_loss_days(snapshots, roundtrips, days),
        _eval_g5_no_donottrade(paper_trades_window),
        _eval_g6_engine_uptime(snapshots, days),
        _eval_g7_verdict_freshness(as_of),
    ]


def evaluate(as_of: date | None = None) -> ROIReadinessResult:
    """
    Main entry point. Evaluates all 7 gates as of `as_of` (default: today).

    Returns an ROIReadinessResult.
    """
    if as_of is None:
        as_of = date.today()

    days = _trading_days_window(as_of, WINDOW_TRADING_DAYS)
    snapshots = _load_pnl_snapshots(days)
    paper_trades_window = _load_paper_trades_window(days)
    roundtrips = _pair_trades_to_roundtrips(paper_trades_window)

    gates = _run_all_gates(
        as_of=as_of,
        days=days,
        snapshots=snapshots,
        roundtrips=roundtrips,
        paper_trades_window=paper_trades_window,
    )

    pass_count = sum(1 for g in gates if g.passed)

    if pass_count == 7:
        status = "GREEN"
    elif pass_count >= 5:
        status = "YELLOW"
    else:
        status = "RED"

    streak = compute_consecutive_passing_days(
        as_of=as_of,
        days=days,
        snapshots=snapshots,
        roundtrips=roundtrips,
        paper_trades_window=paper_trades_window,
    )
    days_to_live = max(0, STREAK_TARGET - streak)

    return ROIReadinessResult(
        snapshot_date=as_of,
        status=status,
        pass_count=pass_count,
        gates=gates,
        consecutive_passing_days=streak,
        days_to_live=days_to_live,
    )


# ---------------------------------------------------------------------------
# CLI (for direct invocation)
# ---------------------------------------------------------------------------


def _main() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="ROI Readiness Evaluator")
    parser.add_argument("--date", default=None, help="Evaluation date YYYY-MM-DD (default: today)")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args()

    as_of = date.today()
    if args.date:
        try:
            as_of = date.fromisoformat(args.date)
        except ValueError:
            print(f"ERROR: invalid --date {args.date!r}", file=sys.stderr)
            return 1

    result = evaluate(as_of)

    if args.json:
        out = asdict(result)
        out["snapshot_date"] = result.snapshot_date.isoformat()
        # gates list: convert to plain dicts
        print(json.dumps(out, indent=2, default=str))
    else:
        _print_table(result)

    return 0 if result.status == "GREEN" else 1


def _print_table(result: ROIReadinessResult) -> None:
    print()
    print("=" * 80)
    print("ROI READINESS GAUGE — $250/day × 14-day Live-Trading Trigger")
    print("=" * 80)
    for g in result.gates:
        marker = "PASS" if g.passed else "FAIL"
        print(f"\n[{marker}] {g.gate_id}: {g.name}")
        print(f"       Observed:  {g.observed}")
        print(f"       Threshold: {g.threshold}")
        if g.notes:
            print(f"       Notes:     {g.notes}")
    print()
    print("=" * 80)
    print(f"GATES: {result.pass_count}/7 PASS  |  STATUS: {result.status}")
    print(
        f"Streak: {result.consecutive_passing_days} consecutive passing day(s)  "
        f"|  Days to live: {result.days_to_live}"
    )
    print("=" * 80)
    print()


if __name__ == "__main__":
    import sys

    sys.exit(_main())
