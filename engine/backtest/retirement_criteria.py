"""
Strategy Retirement Criteria — PASS->RETIRE degradation thresholds.

Three-tier escalation system for strategies already in active paper/live trading:

    WATCH   — mild degradation; continue trading, increase monitoring cadence
    REVIEW  — significant degradation; pause entries, manual investigation required
    RETIRE  — strong statistical evidence of edge decay; halt strategy, re-verify from scratch

Thresholds are anchored to the gate v2 verdict so they scale appropriately per strategy:
    - Drawdown thresholds are multiples of mc_95th_dd_pct
    - Win-rate floor is derived from p_edge (fraction of OOS windows profitable)
    - Streak thresholds are fixed across all strategies (psychological risk management)

Conservative design philosophy: a false RETIRE signal costs one re-verification run.
Continuing to trade a dead strategy costs real capital. When in doubt, RETIRE.

Usage (from engine/ directory):
    from backtest.retirement_criteria import RetirementCriteria, evaluate

    import json, re
    verdict = json.loads(re.sub(r':\\s*Infinity\\b', ': null',
                                open('data/gate_v2_verdicts/MES_trend_rank11.json').read()))
    criteria = RetirementCriteria.from_verdict(verdict)

    import pandas as pd, sqlite3
    conn = sqlite3.connect('data/jarvis_trader.db')
    pnl_df  = pd.read_sql('SELECT * FROM pnl_snapshots ORDER BY date', conn)
    trade_df = pd.read_sql("SELECT * FROM paper_trades WHERE status='closed' ORDER BY exit_time", conn)
    conn.close()

    signal = evaluate(criteria, pnl_df, trade_df)
    print(signal.tier, signal.triggered, signal.reasons)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Tier constants
# ---------------------------------------------------------------------------

TIER_OK = "OK"
TIER_WATCH = "WATCH"
TIER_REVIEW = "REVIEW"
TIER_RETIRE = "RETIRE"

# Thresholds that are fixed (not derived from verdict)
HARD_STREAK_REVIEW = 4  # consecutive losing days -> REVIEW
HARD_STREAK_RETIRE = 7  # consecutive losing days -> RETIRE
ROLLING_21D_WIN_RATE_WATCH = 0.30  # win rate below this -> WATCH
ROLLING_21D_WIN_RATE_REVIEW = 0.20  # win rate below this -> REVIEW
ROLLING_90D_PF_RETIRE = 0.75  # rolling PF below this (with sufficient trades) -> RETIRE
ROLLING_90D_MIN_TRADES = 30  # minimum trades in 90d window for PF signal to count
ROLLING_21D_PF_REVIEW = 0.90  # rolling PF below this -> REVIEW signal


# ---------------------------------------------------------------------------
# Criteria dataclass
# ---------------------------------------------------------------------------


@dataclass
class RetirementCriteria:
    """Retirement thresholds, parameterized from a gate v2 verdict.

    Attributes:
        symbol:         Strategy symbol (e.g., "MES")
        strategy_key:   Verdict filename stem (e.g., "MES_trend_rank11")
        mc_95th_dd_pct: Monte Carlo 95th-pct max drawdown from verdict (0-100 scale)
        p_edge:         Fraction of OOS windows profitable from verdict (0.0-1.0)
        verdict_date:   ISO date string of verdict creation

        dd_watch_pct:   Portfolio DD pct triggering WATCH (1.5x mc_95th_dd)
        dd_review_pct:  Portfolio DD pct triggering REVIEW (2.0x mc_95th_dd)
        dd_retire_pct:  Single-day loss pct triggering RETIRE (3.0x mc_95th_dd)
    """

    symbol: str
    strategy_key: str
    mc_95th_dd_pct: float
    p_edge: float
    verdict_date: str

    dd_watch_pct: float = field(init=False)
    dd_review_pct: float = field(init=False)
    dd_retire_pct: float = field(init=False)

    def __post_init__(self) -> None:
        self.dd_watch_pct = round(self.mc_95th_dd_pct * 1.5, 2)
        self.dd_review_pct = round(self.mc_95th_dd_pct * 2.0, 2)
        self.dd_retire_pct = round(self.mc_95th_dd_pct * 3.0, 2)

    @classmethod
    def from_verdict(cls, verdict: dict) -> "RetirementCriteria":
        """Build from a loaded gate v2 verdict dict."""
        m = verdict.get("gate_v2_metrics") or {}
        dd = m.get("mc_95th_dd_pct")
        p_edge = m.get("p_edge")

        # Fallback: parse from core_reasons strings if metrics block absent
        if dd is None or p_edge is None:
            import re as _re

            core = " ".join((verdict.get("gate_v2") or {}).get("core_reasons") or [])
            if dd is None:
                m2 = _re.search(r"mc_95th_dd_pct=([\d.]+)", core)
                dd = float(m2.group(1)) if m2 else 5.0
            if p_edge is None:
                m2 = _re.search(r"p_positive_edge=([\d.]+)", core)
                p_edge = float(m2.group(1)) if m2 else 0.95

        return cls(
            symbol=verdict.get("symbol", "UNKNOWN"),
            strategy_key=f"{verdict.get('symbol', 'UNKNOWN')}_{verdict.get('family', 'unknown')}_{verdict.get('rank', 'r0')}",
            mc_95th_dd_pct=float(dd or 5.0),
            p_edge=float(p_edge or 0.95),
            verdict_date=(verdict.get("created_at") or "unknown")[:10],
        )


# ---------------------------------------------------------------------------
# Signal dataclass
# ---------------------------------------------------------------------------


@dataclass
class RetirementSignal:
    """Result of a retirement evaluation.

    Attributes:
        tier:       "OK" | "WATCH" | "REVIEW" | "RETIRE"
        triggered:  True if any threshold was crossed
        reasons:    List of human-readable reason strings, one per triggered criterion
        metrics:    Dict of computed metrics used in evaluation (for logging/reporting)
        as_of:      Evaluation date
    """

    tier: str
    triggered: bool
    reasons: list[str]
    metrics: dict
    as_of: date


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------


def evaluate(
    criteria: RetirementCriteria,
    pnl_df: pd.DataFrame,
    trade_df: pd.DataFrame,
    as_of: Optional[date] = None,
) -> RetirementSignal:
    """Evaluate retirement criteria against live pnl_snapshots + paper_trades data.

    Args:
        criteria:  RetirementCriteria (built from verdict via from_verdict())
        pnl_df:    DataFrame from pnl_snapshots table (must have 'date', 'daily_pnl',
                   'portfolio_equity', 'consecutive_losses' columns)
        trade_df:  DataFrame from paper_trades/trades table (must have 'pnl', 'symbol',
                   'exit_time' or 'date' column) for the relevant symbol
        as_of:     Evaluation date; defaults to today

    Returns:
        RetirementSignal with tier, reasons, and metrics
    """
    if as_of is None:
        as_of = date.today()

    reasons: list[str] = []
    tier = TIER_OK
    metrics: dict = {}

    # ---- Normalize DataFrames ----
    pnl_df = pnl_df.copy()
    if pnl_df.empty or "date" not in pnl_df.columns:
        pnl_df = pd.DataFrame(
            columns=["date", "daily_pnl", "portfolio_equity", "peak_equity", "consecutive_losses"]
        )
    else:
        pnl_df["date"] = pd.to_datetime(pnl_df["date"]).dt.date
    pnl_df = pnl_df[pnl_df["date"] <= as_of].sort_values("date")

    trade_df = trade_df.copy()
    time_col = "exit_time" if "exit_time" in trade_df.columns else "date"
    if time_col in trade_df.columns:
        trade_df["_date"] = pd.to_datetime(trade_df[time_col]).dt.date
    else:
        trade_df["_date"] = as_of

    # Filter trades to this strategy's symbol
    if "symbol" in trade_df.columns:
        trade_df = trade_df[trade_df["symbol"] == criteria.symbol]

    # ---- Lookback windows ----
    cutoff_21d = as_of - timedelta(days=30)  # ~21 trading days in 30 calendar days
    cutoff_90d = as_of - timedelta(days=125)  # ~90 trading days in 125 calendar days

    pnl_21d = pnl_df[pnl_df["date"] >= cutoff_21d]
    trades_21d = trade_df[trade_df["_date"] >= cutoff_21d]
    trades_90d = trade_df[trade_df["_date"] >= cutoff_90d]

    # ---- Metric 1: Consecutive losing days (latest streak) ----
    streak = 0
    if not pnl_df.empty and "consecutive_losses" in pnl_df.columns:
        streak = int(pnl_df["consecutive_losses"].iloc[-1] or 0)
    elif not pnl_df.empty and "daily_pnl" in pnl_df.columns:
        # Compute from daily_pnl
        recent = pnl_df["daily_pnl"].tolist()
        streak = 0
        for v in reversed(recent):
            if v is not None and float(v) < 0:
                streak += 1
            else:
                break
    metrics["consecutive_loss_days"] = streak

    if streak >= HARD_STREAK_RETIRE:
        reasons.append(
            f"Consecutive losing days={streak} >= {HARD_STREAK_RETIRE} (RETIRE threshold)"
        )
        tier = TIER_RETIRE
    elif streak >= HARD_STREAK_REVIEW:
        reasons.append(
            f"Consecutive losing days={streak} >= {HARD_STREAK_REVIEW} (REVIEW threshold)"
        )
        tier = _escalate(tier, TIER_REVIEW)

    # ---- Metric 2: Rolling 21-day win rate ----
    win_rate_21d: Optional[float] = None
    if not trades_21d.empty and "pnl" in trades_21d.columns:
        pnls = trades_21d["pnl"].dropna().astype(float)
        if len(pnls) >= 5:
            win_rate_21d = float((pnls > 0).mean())
    metrics["win_rate_21d"] = win_rate_21d

    if win_rate_21d is not None:
        if win_rate_21d < ROLLING_21D_WIN_RATE_REVIEW:
            reasons.append(
                f"21d win rate={win_rate_21d:.1%} < {ROLLING_21D_WIN_RATE_REVIEW:.0%} (REVIEW)"
            )
            tier = _escalate(tier, TIER_REVIEW)
        elif win_rate_21d < ROLLING_21D_WIN_RATE_WATCH:
            reasons.append(
                f"21d win rate={win_rate_21d:.1%} < {ROLLING_21D_WIN_RATE_WATCH:.0%} (WATCH)"
            )
            tier = _escalate(tier, TIER_WATCH)

    # ---- Metric 3: Rolling 21-day PF ----
    pf_21d: Optional[float] = None
    if not trades_21d.empty and "pnl" in trades_21d.columns:
        pnls = trades_21d["pnl"].dropna().astype(float)
        wins = pnls[pnls > 0].sum()
        losses = abs(pnls[pnls < 0].sum())
        if losses > 0:
            pf_21d = float(wins / losses)
        elif wins > 0:
            pf_21d = float("inf")
    metrics["pf_21d"] = pf_21d

    if pf_21d is not None and pf_21d != float("inf") and pf_21d < ROLLING_21D_PF_REVIEW:
        reasons.append(f"21d rolling PF={pf_21d:.3f} < {ROLLING_21D_PF_REVIEW} (REVIEW)")
        tier = _escalate(tier, TIER_REVIEW)

    # ---- Metric 4: Rolling 90-day PF (with trade-count gate) ----
    pf_90d: Optional[float] = None
    n_trades_90d = 0
    if not trades_90d.empty and "pnl" in trades_90d.columns:
        pnls_90 = trades_90d["pnl"].dropna().astype(float)
        n_trades_90d = len(pnls_90)
        wins = pnls_90[pnls_90 > 0].sum()
        losses = abs(pnls_90[pnls_90 < 0].sum())
        if losses > 0:
            pf_90d = float(wins / losses)
        elif wins > 0:
            pf_90d = float("inf")
    metrics["pf_90d"] = pf_90d
    metrics["n_trades_90d"] = n_trades_90d

    if pf_90d is not None and pf_90d != float("inf"):
        if n_trades_90d >= ROLLING_90D_MIN_TRADES and pf_90d < ROLLING_90D_PF_RETIRE:
            reasons.append(
                f"90d rolling PF={pf_90d:.3f} < {ROLLING_90D_PF_RETIRE} "
                f"with {n_trades_90d} trades >= {ROLLING_90D_MIN_TRADES} (RETIRE)"
            )
            tier = _escalate(tier, TIER_RETIRE)

    # ---- Metric 5: Portfolio drawdown vs mc_95th_dd thresholds ----
    max_dd_pct: Optional[float] = None
    if (
        not pnl_21d.empty
        and "portfolio_equity" in pnl_21d.columns
        and "peak_equity" in pnl_21d.columns
    ):
        eq = pnl_21d["portfolio_equity"].dropna().astype(float)
        peak = pnl_21d["peak_equity"].dropna().astype(float)
        if len(eq) > 0 and len(peak) > 0 and peak.iloc[-1] > 0:
            max_dd_pct = float((peak - eq).clip(lower=0).max() / peak.iloc[0] * 100)
    metrics["max_dd_pct_21d"] = max_dd_pct

    if max_dd_pct is not None:
        if max_dd_pct > criteria.dd_retire_pct:
            reasons.append(
                f"21d max drawdown={max_dd_pct:.1f}% > dd_retire_pct={criteria.dd_retire_pct:.1f}% "
                f"(3x mc_95th_dd={criteria.mc_95th_dd_pct:.1f}%) (RETIRE)"
            )
            tier = _escalate(tier, TIER_RETIRE)
        elif max_dd_pct > criteria.dd_review_pct:
            reasons.append(
                f"21d max drawdown={max_dd_pct:.1f}% > dd_review_pct={criteria.dd_review_pct:.1f}% "
                f"(2x mc_95th_dd={criteria.mc_95th_dd_pct:.1f}%) (REVIEW)"
            )
            tier = _escalate(tier, TIER_REVIEW)
        elif max_dd_pct > criteria.dd_watch_pct:
            reasons.append(
                f"21d max drawdown={max_dd_pct:.1f}% > dd_watch_pct={criteria.dd_watch_pct:.1f}% "
                f"(1.5x mc_95th_dd={criteria.mc_95th_dd_pct:.1f}%) (WATCH)"
            )
            tier = _escalate(tier, TIER_WATCH)

    # ---- Metric 6: Single-day loss > 3x mc_95th_dd ----
    worst_day_pct: Optional[float] = None
    if (
        not pnl_21d.empty
        and "daily_pnl" in pnl_21d.columns
        and "portfolio_equity" in pnl_21d.columns
    ):
        pnl_vals = pnl_21d["daily_pnl"].dropna().astype(float)
        eq_vals = pnl_21d["portfolio_equity"].dropna().astype(float)
        if len(pnl_vals) > 0 and len(eq_vals) > 0 and eq_vals.mean() > 0:
            worst_day_abs = abs(pnl_vals.min())
            worst_day_pct = float(worst_day_abs / eq_vals.mean() * 100)
    metrics["worst_single_day_pct"] = worst_day_pct

    if worst_day_pct is not None and worst_day_pct > criteria.dd_retire_pct:
        reasons.append(
            f"Worst single-day loss={worst_day_pct:.1f}% > dd_retire_pct={criteria.dd_retire_pct:.1f}% (RETIRE)"
        )
        tier = _escalate(tier, TIER_RETIRE)

    return RetirementSignal(
        tier=tier,
        triggered=(tier != TIER_OK),
        reasons=reasons,
        metrics=metrics,
        as_of=as_of,
    )


def _escalate(current: str, proposed: str) -> str:
    """Return the higher-severity tier."""
    _order = {TIER_OK: 0, TIER_WATCH: 1, TIER_REVIEW: 2, TIER_RETIRE: 3}
    return current if _order[current] >= _order[proposed] else proposed


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------


def format_signal(signal: RetirementSignal, criteria: RetirementCriteria) -> str:
    """Render a human-readable summary of a RetirementSignal."""
    lines = [
        f"Retirement check — {criteria.strategy_key} as of {signal.as_of}",
        f"Tier: {signal.tier}  |  Triggered: {signal.triggered}",
        "",
        "Metrics:",
    ]
    for k, v in signal.metrics.items():
        if v is None:
            lines.append(f"  {k}: n/a")
        elif isinstance(v, float):
            lines.append(f"  {k}: {v:.3f}")
        else:
            lines.append(f"  {k}: {v}")
    if signal.reasons:
        lines.append("")
        lines.append("Triggered conditions:")
        for r in signal.reasons:
            lines.append(f"  - {r}")
    else:
        lines.append("")
        lines.append("No conditions triggered.")
    lines.append("")
    lines.append("Thresholds (from verdict):")
    lines.append(f"  mc_95th_dd_pct : {criteria.mc_95th_dd_pct:.2f}%")
    lines.append(f"  dd_watch_pct   : {criteria.dd_watch_pct:.2f}%  (1.5x mc_dd)")
    lines.append(f"  dd_review_pct  : {criteria.dd_review_pct:.2f}%  (2.0x mc_dd)")
    lines.append(f"  dd_retire_pct  : {criteria.dd_retire_pct:.2f}%  (3.0x mc_dd)")
    lines.append(f"  verdict_date   : {criteria.verdict_date}")
    return "\n".join(lines)
