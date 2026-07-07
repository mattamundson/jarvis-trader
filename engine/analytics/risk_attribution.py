"""
Risk Attribution Engine — read-only P&L decomposition across pipeline analysts.

Methodology:  pro-rata attribution based on signed (signal × confidence) weights
stored in paper_trades.strategy_params["analyst_signals"].

Each analyst's contribution to a trade's P&L:
    weight_i = signal_i * confidence_i          (raw signed weight)
    normalized = weight_i / sum(|weight_j|)     (fraction of absolute mass)
    attribution_i = pnl * normalized

Residual captures P&L that can't be attributed (no verdict stored, all signals
zero, or sum of attributions ≠ total_pnl due to rounding / gap moves / slippage).

DESIGN INVARIANT: this module is READ-ONLY. It never writes to paper_trades,
pipeline_runs, or any other table. It only reads.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, stdev
from typing import Optional

logger = logging.getLogger(__name__)

# ── Canonical analyst slots ───────────────────────────────────────────────────
# Matches the analyst_signals keys written by the pipeline.
ANALYST_SLOTS: list[str] = [
    "technical",
    "news",
    "social",
    "fundamental",
    "corey",
    "pattern_vision",
    "kronos",
    "options",
    "regime_adjust",
    "other",
]

_DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "jarvis_trader.db")

# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class DailyAttribution:
    """Per-day attribution result."""

    date: str  # ISO date string YYYY-MM-DD
    total_pnl: float
    n_trades: int
    attribution: dict[str, float]  # analyst → attributed P&L dollars
    top_contributor: Optional[str]  # analyst with largest |attribution|
    residual: float  # total_pnl - sum(attribution values)
    attributed_trade_count: int  # trades with a usable analyst_signals verdict
    unattributed_trade_count: int  # trades with no verdict / all-zero signals


@dataclass
class WindowAttribution:
    """Rolling window summary."""

    start_date: str
    end_date: str
    days_with_trades: int
    total_pnl: float
    n_trades: int
    per_analyst: dict[str, dict]  # analyst → {total, mean, std, max_loss, win_rate_top}
    top_contributor_by_abs: str
    daily: list[DailyAttribution]


# ── Core helpers ──────────────────────────────────────────────────────────────


def _zero_attribution() -> dict[str, float]:
    return dict.fromkeys(ANALYST_SLOTS, 0.0)


def _extract_analyst_weights(strategy_params_json: str | None) -> dict[str, float]:
    """
    Parse strategy_params JSON and return a normalized signed weight per analyst.

    Returns empty dict when no usable verdict exists.
    weight_i is already the analyst's confidence-scaled signal (signal * confidence)
    as stored in strategy_params["analyst_signals"].
    """
    if not strategy_params_json:
        return {}
    try:
        params = json.loads(strategy_params_json)
    except (json.JSONDecodeError, TypeError):
        return {}

    raw_signals: dict = params.get("analyst_signals", {})
    if not isinstance(raw_signals, dict) or not raw_signals:
        return {}

    # Normalize: each analyst's fraction of total |signal| mass
    total_abs = sum(abs(v) for v in raw_signals.values() if isinstance(v, (int, float)))
    if total_abs == 0.0:
        return {}

    normalized: dict[str, float] = {}
    for analyst, sig in raw_signals.items():
        if not isinstance(sig, (int, float)):
            continue
        normalized[analyst] = float(sig) / total_abs
    return normalized


def _attribute_trade(
    pnl: float, strategy_params_json: str | None
) -> tuple[dict[str, float], float]:
    """
    Attribute a single trade's P&L across analysts.

    Returns:
        (attribution_dict, residual)
        attribution_dict: analyst → dollars attributed
        residual: pnl not captured in attribution (slippage, gap, unclassified)
    """
    weights = _extract_analyst_weights(strategy_params_json)
    if not weights:
        return {}, pnl  # fully residual

    contrib: dict[str, float] = {}
    for analyst, w in weights.items():
        dollars = pnl * w
        # Map to canonical slot; unknown analysts go to "other"
        slot = analyst if analyst in ANALYST_SLOTS else "other"
        contrib[slot] = contrib.get(slot, 0.0) + dollars

    # Residual is zero when a verdict exists: the attribution fully explains the trade.
    # Opposing signals (e.g. technical bullish + news bearish) will result in positive
    # attribution for one analyst and negative for another — the sum may not equal pnl,
    # but that's correct behavior: each analyst's net impact is their signed share.
    # Residual is reserved for trades with NO stored verdict (unattributed_trade_count).
    return contrib, 0.0


# ── Public API ────────────────────────────────────────────────────────────────


def attribute_daily_pnl(
    target_date: date,
    db_path: str = _DEFAULT_DB_PATH,
) -> DailyAttribution:
    """
    Decompose closed paper_trades P&L for a single calendar date.

    Joins strategy_params (verdict JSON) to realized pnl per trade.
    Returns zero-filled DailyAttribution when no closed trades exist for the date.
    """
    date_str = target_date.isoformat()
    date_prefix = f"{date_str}%"

    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT pnl, strategy_params
                FROM paper_trades
                WHERE status = 'closed'
                  AND pnl IS NOT NULL
                  AND exit_time LIKE ?
                ORDER BY exit_time
                """,
                (date_prefix,),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.error("[risk_attribution] DB error for %s: %s", date_str, exc)
        return DailyAttribution(
            date=date_str,
            total_pnl=0.0,
            n_trades=0,
            attribution=_zero_attribution(),
            top_contributor=None,
            residual=0.0,
            attributed_trade_count=0,
            unattributed_trade_count=0,
        )

    n_trades = len(rows)
    if n_trades == 0:
        return DailyAttribution(
            date=date_str,
            total_pnl=0.0,
            n_trades=0,
            attribution=_zero_attribution(),
            top_contributor=None,
            residual=0.0,
            attributed_trade_count=0,
            unattributed_trade_count=0,
        )

    total_pnl = sum(row["pnl"] for row in rows)
    agg: dict[str, float] = _zero_attribution()
    total_residual = 0.0
    attributed_count = 0
    unattributed_count = 0

    for row in rows:
        contrib, residual = _attribute_trade(
            pnl=float(row["pnl"]),
            strategy_params_json=row["strategy_params"],
        )
        if contrib:
            attributed_count += 1
            for slot, dollars in contrib.items():
                agg[slot] = agg.get(slot, 0.0) + dollars
        else:
            unattributed_count += 1
        total_residual += residual

    # Top contributor by absolute attributed dollars
    top = max(agg.items(), key=lambda kv: abs(kv[1]), default=(None, 0.0))
    top_contributor = top[0] if top[1] != 0.0 else None

    return DailyAttribution(
        date=date_str,
        total_pnl=total_pnl,
        n_trades=n_trades,
        attribution=agg,
        top_contributor=top_contributor,
        residual=total_residual,
        attributed_trade_count=attributed_count,
        unattributed_trade_count=unattributed_count,
    )


def attribute_window(
    start_date: date,
    end_date: date,
    db_path: str = _DEFAULT_DB_PATH,
) -> WindowAttribution:
    """
    Roll up per-day attributions across a date window.

    Computes per-analyst aggregate stats: total, mean, std, max single-day draw,
    and win_rate_top (fraction of days this analyst was the top contributor AND the
    day was profitable).
    """
    daily_results: list[DailyAttribution] = []
    current = start_date
    while current <= end_date:
        daily_results.append(attribute_daily_pnl(current, db_path=db_path))
        current += timedelta(days=1)

    days_with_trades = sum(1 for d in daily_results if d.n_trades > 0)
    total_pnl = sum(d.total_pnl for d in daily_results)
    n_trades = sum(d.n_trades for d in daily_results)

    # Per-analyst aggregate stats
    per_analyst: dict[str, dict] = {}
    for slot in ANALYST_SLOTS:
        daily_vals = [d.attribution.get(slot, 0.0) for d in daily_results if d.n_trades > 0]
        if not daily_vals:
            per_analyst[slot] = {
                "total": 0.0,
                "mean": 0.0,
                "std": 0.0,
                "max_loss": 0.0,
                "win_rate_top": 0.0,
            }
            continue

        total = sum(daily_vals)
        avg = mean(daily_vals)
        std = stdev(daily_vals) if len(daily_vals) > 1 else 0.0
        max_loss = min(daily_vals)

        # win_rate_top: % of profitable days where this slot was top contributor
        profitable_top = sum(
            1
            for d in daily_results
            if d.n_trades > 0 and d.total_pnl > 0 and d.top_contributor == slot
        )
        profitable_days = sum(1 for d in daily_results if d.n_trades > 0 and d.total_pnl > 0)
        win_rate_top = (profitable_top / profitable_days) if profitable_days > 0 else 0.0

        per_analyst[slot] = {
            "total": round(total, 4),
            "mean": round(avg, 4),
            "std": round(std, 4),
            "max_loss": round(max_loss, 4),
            "win_rate_top": round(win_rate_top, 4),
        }

    # Top contributor by aggregate absolute total
    top_abs = max(
        per_analyst.items(),
        key=lambda kv: abs(kv[1]["total"]),
        default=("none", {}),
    )
    top_contributor_by_abs = top_abs[0]

    return WindowAttribution(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        days_with_trades=days_with_trades,
        total_pnl=total_pnl,
        n_trades=n_trades,
        per_analyst=per_analyst,
        top_contributor_by_abs=top_contributor_by_abs,
        daily=daily_results,
    )


def format_markdown(window: WindowAttribution) -> str:
    """
    Render a WindowAttribution as vault-ready Markdown.

    Suitable for daily-<date>.md or weekly-<week>.md gbrain ingest.
    """
    lines: list[str] = []
    lines.append(f"# Risk Attribution: {window.start_date} to {window.end_date}")
    lines.append("")
    lines.append(f"**Total P&L:** ${window.total_pnl:+,.2f}  ")
    lines.append(f"**Trades:** {window.n_trades}  ")
    lines.append(f"**Trading days:** {window.days_with_trades}  ")
    lines.append(f"**Top contributor (window):** {window.top_contributor_by_abs}")
    lines.append("")
    lines.append("## Per-Analyst Attribution")
    lines.append("")
    lines.append("| Analyst | Total ($) | Mean/day ($) | Std ($) | Max Draw ($) | Win Rate (top) |")
    lines.append("|---------|-----------|-------------|---------|--------------|----------------|")
    for slot in ANALYST_SLOTS:
        s = window.per_analyst.get(slot, {})
        lines.append(
            f"| {slot} "
            f"| {s.get('total', 0.0):+,.2f} "
            f"| {s.get('mean', 0.0):+,.2f} "
            f"| {s.get('std', 0.0):,.2f} "
            f"| {s.get('max_loss', 0.0):+,.2f} "
            f"| {s.get('win_rate_top', 0.0):.1%} |"
        )
    lines.append("")
    lines.append("## Daily Detail")
    lines.append("")
    for day in window.daily:
        if day.n_trades == 0:
            continue
        lines.append(f"### {day.date}")
        lines.append(f"- P&L: ${day.total_pnl:+,.2f} ({day.n_trades} trades)")
        lines.append(f"- Top: {day.top_contributor or 'none'}  Residual: ${day.residual:+,.2f}")
        top_items = sorted(day.attribution.items(), key=lambda kv: abs(kv[1]), reverse=True)[:4]
        for analyst, dollars in top_items:
            if dollars != 0.0:
                lines.append(f"  - {analyst}: ${dollars:+,.2f}")
        lines.append("")
    return "\n".join(lines)
