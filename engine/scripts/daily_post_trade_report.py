"""
Daily post-trade analysis report for JARVIS TRADER.

Runs at 16:30 ET on weekdays. Reads paper_trades.json (append-only positional
log) plus the SQLite DB, generates a structured Markdown report, saves it to
engine/data/post_trade_reports/<YYYY-MM-DD>.md, and posts a Discord summary.

Sections:
  1. Trade summary table (entry/exit pairs, hold_time, PnL)
  2. Headline metrics (win rate, total PnL, avg trade, avg hold, $250/day gauge)
  3. Per-strategy breakdown (MES vs MGC)
  4. Counterfactual — signal regen vs actual fills (missed / extra entries)
  5. Mistake taxonomy — heuristic classification of losing trades
  6. Tomorrow's outlook — current regime state from last bar's SMA positions

Usage:
    python -m engine.scripts.daily_post_trade_report               # today
    python -m engine.scripts.daily_post_trade_report --date 2026-05-07
    python -m engine.scripts.daily_post_trade_report --no-discord  # skip Discord post
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("daily_post_trade_report")

# Add engine dir to sys.path so bare-module imports work (same pattern as all
# other scripts in this directory).
_SCRIPTS_ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ENGINE_DIR))

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ENGINE_DIR = _SCRIPTS_ENGINE_DIR  # alias for clarity below
_PAPER_TRADES_JSON = _ENGINE_DIR / "data" / "paper_trades.json"
_DB_PATH = _ENGINE_DIR / "data" / "jarvis_trader.db"
_REPORT_DIR = _ENGINE_DIR / "data" / "post_trade_reports"

_ET = ZoneInfo("America/New_York")
_UTC = timezone.utc

# ---------------------------------------------------------------------------
# Constants matching engine state
# ---------------------------------------------------------------------------

DO_NOT_TRADE_SYMBOLS: frozenset[str] = frozenset({"MCL", "MNQ", "M2K"})

# Point values for PnL dollar conversion (fallback when DB doesn't have it)
INSTRUMENT_MULTIPLIERS: dict[str, float] = {
    "MES": 5.0,
    "MGC": 10.0,
    "MNQ": 2.0,
    "MCL": 100.0,
    "M2K": 5.0,
}

DAILY_TARGET = 250.0  # proxy for "ready to trade live"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ClosedTrade:
    """Matched buy/sell pair representing one completed round-trip."""

    symbol: str
    side: str  # "buy" = entered long
    quantity: float
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float  # dollar PnL
    slippage_ticks: int = 0
    strategy_params: dict = field(default_factory=dict)

    @property
    def hold_minutes(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds() / 60

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


@dataclass
class SignalEvent:
    """A signal that the strategy generator produced for a given bar."""

    symbol: str
    bar_time: datetime
    signal_type: str  # "ENTRY_NOW" | "EXIT_NOW"
    price: float


# ---------------------------------------------------------------------------
# Trade loading + filtering
# ---------------------------------------------------------------------------


def load_trades_json(path: Path = _PAPER_TRADES_JSON) -> list[dict]:
    """Load raw entries from paper_trades.json. Returns [] if file missing."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "trades" in data:
        return data["trades"]
    return []


def filter_trades_to_date(raw_trades: list[dict], target_date: date) -> list[dict]:
    """Return only raw entries whose timestamp falls on target_date (ET)."""
    result = []
    for t in raw_trades:
        ts_str = t.get("timestamp", "")
        if not ts_str:
            continue
        try:
            dt_utc = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        dt_et = dt_utc.astimezone(_ET)
        if dt_et.date() == target_date:
            result.append(t)
    return result


def _pair_trades(raw: list[dict]) -> list[ClosedTrade]:
    """
    Match buy/sell entries into ClosedTrade pairs.

    Delegates to analytics.paper_trade_pairing.pair_trades which ALWAYS
    recomputes PnL from entry/exit prices × contract multiplier.

    IMPORTANT: the stored ``pnl`` field on sell entries in paper_trades.json
    is in price-point units (writer bug — multiplier was omitted).  Trusting
    that field caused win_rate to read 0.0% even on profitable sessions.
    The shared helper ignores stored_pnl entirely.
    """
    from analytics.paper_trade_pairing import pair_trades as _pair_raw

    raw_closed = _pair_raw(raw)
    result: list[ClosedTrade] = []
    for rt in raw_closed:
        result.append(
            ClosedTrade(
                symbol=rt.symbol,
                side=rt.side,
                quantity=rt.quantity,
                entry_price=rt.entry_price,
                exit_price=rt.exit_price,
                entry_time=rt.entry_time,
                exit_time=rt.exit_time,
                pnl=rt.pnl,
                slippage_ticks=rt.slippage_ticks_exit,
                strategy_params={},
            )
        )
    return result


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def compute_metrics(trades: list[ClosedTrade]) -> dict[str, Any]:
    """Compute headline metrics from a list of closed trades."""
    if not trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "total_pnl": 0.0,
            "avg_trade_pnl": None,
            "biggest_win": None,
            "biggest_loss": None,
            "avg_hold_minutes": None,
            "goal_progress_pct": 0.0,
        }
    pnls = [t.pnl for t in trades]
    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]
    total_pnl = sum(pnls)

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades),
        "total_pnl": total_pnl,
        "avg_trade_pnl": total_pnl / len(trades),
        "biggest_win": max(pnls) if wins else None,
        "biggest_loss": min(pnls) if losses else None,
        "avg_hold_minutes": sum(t.hold_minutes for t in trades) / len(trades),
        "goal_progress_pct": total_pnl / DAILY_TARGET * 100,
    }


# ---------------------------------------------------------------------------
# Per-strategy breakdown
# ---------------------------------------------------------------------------


def compute_strategy_breakdown(trades: list[ClosedTrade]) -> dict[str, dict]:
    """Group metrics by symbol."""
    from collections import defaultdict

    groups: dict[str, list[ClosedTrade]] = defaultdict(list)
    for t in trades:
        groups[t.symbol].append(t)
    return {sym: compute_metrics(group) for sym, group in groups.items()}


# ---------------------------------------------------------------------------
# Counterfactual — signal regen vs actual fills
# ---------------------------------------------------------------------------


def _load_bars_from_db(
    symbol: str, target_date: date, db_path: Path = _DB_PATH
) -> pd.DataFrame | None:
    """
    Load today's 1h OHLCV bars from SQLite.

    Priority:
      1. market_data_bars — populated by MarketDataManager.get_bars() via bars_repository
      2. legacy table names (market_data, bars, ohlcv) for backward compat
    Returns None if no table has data for this date.
    """
    if not db_path.exists():
        return None
    try:
        con = sqlite3.connect(str(db_path))

        # Tier 1: canonical persistence table (migration_024)
        # Fetch a 14-day rolling window so the SMA slow period (200 bars) has
        # enough history; callers filter signal events back to target_date after
        # computing indicators on the full window.
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='market_data_bars'"
        )
        if cur.fetchone():
            df = pd.read_sql_query(
                """
                SELECT ts_utc AS timestamp, open, high, low, close, volume
                FROM market_data_bars
                WHERE symbol = ? AND interval = '1h'
                  AND ts_utc >= datetime(?, '-14 days')
                ORDER BY ts_utc ASC
                """,
                con,
                params=(symbol.upper(), str(target_date)),
                parse_dates=["timestamp"],
            )
            if not df.empty:
                con.close()
                return df

        # Tier 2: legacy table names used in earlier engine versions
        for tbl in ("market_data", "bars", "ohlcv"):
            cur = con.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{tbl}'")
            if cur.fetchone():
                df = pd.read_sql_query(
                    f"""
                    SELECT timestamp, open, high, low, close, volume
                    FROM {tbl}
                    WHERE symbol = ? AND interval = '1h'
                      AND timestamp >= datetime(?, '-14 days')
                    ORDER BY timestamp ASC
                    """,
                    con,
                    params=(symbol, str(target_date)),
                    parse_dates=["timestamp"],
                )
                if not df.empty:
                    con.close()
                    return df
        con.close()
    except Exception as exc:
        logger.debug("DB bar load failed for %s: %s", symbol, exc)
    return None


def compute_counterfactual(
    trades: list[ClosedTrade],
    target_date: date,
    symbols: list[str] | None = None,
) -> dict[str, list[dict]]:
    """
    Re-run the SMA trend signal generator on today's bars and compare to actual fills.

    Returns:
        {symbol: [{"type": "missed_entry"|"expected_trade", "bar_time": ..., "signal_price": ...}]}
    """
    if symbols is None:
        symbols = ["MES", "MGC"]

    try:
        from backtest.trend_signals import (  # noqa: E402
            SMA_TREND_PARAMS,
            generate_sma_trend_signals,
        )
    except ImportError:
        logger.warning("trend_signals not importable — skipping counterfactual")
        return {}

    result: dict[str, list[dict]] = {}

    for sym in symbols:
        params = SMA_TREND_PARAMS.get(sym)
        if not params:
            continue

        df = _load_bars_from_db(sym, target_date)
        if df is None or df.empty:
            result[sym] = [
                {"type": "no_data", "note": f"No 1h bars found for {sym} on {target_date}"}
            ]
            continue

        # Need enough bars for the slow SMA — if today is sparse, skip
        if len(df) < params["slow"]:
            result[sym] = [
                {
                    "type": "insufficient_bars",
                    "note": f"Only {len(df)} bars; need {params['slow']} for SMA",
                }
            ]
            continue

        df_sig = generate_sma_trend_signals(
            df,
            fast=params["fast"],
            slow=params["slow"],
            atr_trail_mult=params["atr_trail_mult"],
        )

        # Filter signal entries to target_date only — the full df window was loaded
        # to provide enough history for the slow SMA, but we only report on today.
        signal_entries_all = df_sig[df_sig["entry_signal"] == "ENTRY_NOW"].copy()
        target_date_ts = pd.Timestamp(target_date)
        signal_entries = signal_entries_all[
            signal_entries_all["timestamp"].dt.normalize() == target_date_ts
        ]

        actual_entry_times = {t.entry_time.replace(tzinfo=None) for t in trades if t.symbol == sym}

        events: list[dict] = []
        for _, row in signal_entries.iterrows():
            # Use the timestamp column directly — row.name is a RangeIndex integer,
            # which would produce a 1970-epoch datetime.
            bar_ts = pd.Timestamp(row["timestamp"]).to_pydatetime().replace(tzinfo=None)
            bar_ts_floor = bar_ts.replace(minute=0, second=0, microsecond=0)
            # Consider "filled" if any actual entry was within ±30 minutes of the signal bar
            matched = any(
                abs((act - bar_ts_floor).total_seconds()) <= 1800 for act in actual_entry_times
            )
            if matched:
                events.append(
                    {
                        "type": "expected_trade",
                        "bar_time": bar_ts.isoformat(),
                        "signal_price": float(row["close"]),
                    }
                )
            else:
                events.append(
                    {
                        "type": "missed_entry",
                        "bar_time": bar_ts.isoformat(),
                        "signal_price": float(row["close"]),
                        "note": "Signal fired but no matching actual fill",
                    }
                )
        result[sym] = events

    return result


# ---------------------------------------------------------------------------
# Mistake taxonomy
# ---------------------------------------------------------------------------

_SLIPPAGE_THRESHOLD_TICKS = 1


def classify_mistake(trade: ClosedTrade) -> str:
    """
    Heuristic classification for a losing trade.

    Returns one of:
      wrong_symbol   — symbol is in DO_NOT_TRADE_SYMBOLS
      bad_fill       — slippage_ticks > threshold (execution issue)
      bad_signal     — strategy-approved symbol, loss with normal fill
    """
    if trade.symbol in DO_NOT_TRADE_SYMBOLS:
        return "wrong_symbol"
    if trade.slippage_ticks > _SLIPPAGE_THRESHOLD_TICKS:
        return "bad_fill"
    return "bad_signal"


def compute_mistake_taxonomy(trades: list[ClosedTrade]) -> list[dict]:
    """Return taxonomy rows for all losing trades."""
    rows = []
    for t in trades:
        if t.is_win:
            continue
        rows.append(
            {
                "symbol": t.symbol,
                "entry_time": t.entry_time.isoformat(),
                "pnl": t.pnl,
                "slippage_ticks": t.slippage_ticks,
                "cause": classify_mistake(t),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Tomorrow's outlook
# ---------------------------------------------------------------------------


def compute_outlook(target_date: date, symbols: list[str] | None = None) -> dict[str, str]:
    """
    Return a one-line outlook per symbol based on current SMA regime.
    Reads most recent bars from DB and checks whether fast > slow SMA.
    """
    if symbols is None:
        symbols = ["MES", "MGC"]

    try:
        from backtest.trend_signals import (  # noqa: E402
            SMA_TREND_PARAMS,
            generate_sma_trend_signals,
        )
    except ImportError:
        return dict.fromkeys(symbols, "trend_signals not importable")

    outlooks: dict[str, str] = {}
    if not _DB_PATH.exists():
        return dict.fromkeys(symbols, "DB unavailable")

    try:
        con = sqlite3.connect(str(_DB_PATH))
        for sym in symbols:
            params = SMA_TREND_PARAMS.get(sym)
            if not params:
                outlooks[sym] = "no params configured"
                continue

            df = None
            # Tier 1: canonical bar persistence table (migration_024)
            cur = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='market_data_bars'"
            )
            if cur.fetchone():
                _df = pd.read_sql_query(
                    f"""
                    SELECT ts_utc AS timestamp, open, high, low, close, volume
                    FROM market_data_bars
                    WHERE symbol = ? AND interval = '1h'
                    ORDER BY ts_utc DESC
                    LIMIT {params['slow'] * 2}
                    """,
                    con,
                    params=(sym.upper(),),
                    parse_dates=["timestamp"],
                )
                if not _df.empty:
                    df = _df.sort_values("timestamp").reset_index(drop=True)

            # Tier 2: legacy table names
            if df is None or df.empty:
                for tbl in ("market_data", "bars", "ohlcv"):
                    cur = con.execute(
                        f"SELECT name FROM sqlite_master WHERE type='table' AND name='{tbl}'"
                    )
                    if cur.fetchone():
                        _df = pd.read_sql_query(
                            f"""
                            SELECT timestamp, open, high, low, close, volume
                            FROM {tbl}
                            WHERE symbol = ? AND interval = '1h'
                            ORDER BY timestamp DESC
                            LIMIT {params['slow'] * 2}
                            """,
                            con,
                            params=(sym,),
                            parse_dates=["timestamp"],
                        )
                        if not _df.empty:
                            df = _df.sort_values("timestamp").reset_index(drop=True)
                            break

            if df is None or df.empty or len(df) < params["slow"]:
                outlooks[sym] = "insufficient bar history for SMA outlook"
                continue

            df_sig = generate_sma_trend_signals(
                df,
                fast=params["fast"],
                slow=params["slow"],
                atr_trail_mult=params["atr_trail_mult"],
            )
            last = df_sig.iloc[-1]
            regime = last.get("regime", "UNKNOWN")
            bias = last.get("bias", "UNKNOWN")
            atr_val = last.get("atr", float("nan"))
            close_val = float(df["close"].iloc[-1])
            if pd.notna(atr_val):
                outlooks[sym] = (
                    f"regime={regime} bias={bias} "
                    f"close={close_val:.2f} ATR={atr_val:.2f} "
                    f"(fast={params['fast']}/slow={params['slow']})"
                )
            else:
                outlooks[sym] = f"regime={regime} bias={bias} close={close_val:.2f}"
        con.close()
    except Exception as exc:
        logger.debug("Outlook query failed: %s", exc)
        for sym in symbols:
            if sym not in outlooks:
                outlooks[sym] = f"error: {exc}"

    return outlooks


# ---------------------------------------------------------------------------
# Markdown report renderer
# ---------------------------------------------------------------------------


def _FMT_MONEY(x):
    return f"${x:+.2f}" if x is not None else "—"


def _FMT_PCT(x):
    return f"{x:.1f}%" if x is not None else "—"


def render_report(
    report_date: date,
    trades: list[ClosedTrade],
    metrics: dict[str, Any],
    strategy_breakdown: dict[str, dict],
    counterfactual: dict[str, list[dict]],
    taxonomy: list[dict],
    outlook: dict[str, str],
) -> str:
    lines: list[str] = []

    lines.append(f"# JARVIS Daily Post-Trade Report — {report_date.isoformat()}")
    lines.append(f"*Generated {datetime.now(_UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}*")
    lines.append("")

    # --- 1. Trade summary table ---
    lines.append("## 1. Trade Summary")
    if not trades:
        lines.append("*No completed round-trips for this session.*")
    else:
        lines.append("| Symbol | Side | Qty | Entry | Exit | PnL | Hold |")
        lines.append("|--------|------|-----|-------|------|-----|------|")
        for t in sorted(trades, key=lambda x: x.entry_time):
            hold = f"{t.hold_minutes:.0f}m"
            pnl_fmt = _FMT_MONEY(t.pnl)
            lines.append(
                f"| {t.symbol} | {t.side} | {int(t.quantity)} "
                f"| {t.entry_price:.2f} | {t.exit_price:.2f} "
                f"| {pnl_fmt} | {hold} |"
            )
    lines.append("")

    # --- 2. Headline metrics ---
    lines.append("## 2. Headline Metrics")
    m = metrics
    total_pnl = m["total_pnl"]
    goal_pct = m["goal_progress_pct"]
    gauge_bar = "█" * min(int(goal_pct / 5), 20) + "░" * (20 - min(int(goal_pct / 5), 20))
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total PnL | {_FMT_MONEY(total_pnl)} |")
    lines.append(f"| $250/day goal | `{gauge_bar}` {goal_pct:.1f}% |")
    lines.append(f"| Total Trades | {m['total_trades']} |")
    lines.append(
        f"| Win Rate | {_FMT_PCT(m['win_rate'] * 100 if m['win_rate'] is not None else None)} |"
    )
    lines.append(f"| Wins / Losses | {m['wins']} / {m['losses']} |")
    lines.append(f"| Avg Trade PnL | {_FMT_MONEY(m['avg_trade_pnl'])} |")
    lines.append(f"| Biggest Win | {_FMT_MONEY(m['biggest_win'])} |")
    lines.append(f"| Biggest Loss | {_FMT_MONEY(m['biggest_loss'])} |")
    avg_hold = m["avg_hold_minutes"]
    lines.append(f"| Avg Hold Time | {f'{avg_hold:.0f}m' if avg_hold is not None else '—'} |")
    lines.append("")

    # --- 3. Per-strategy breakdown ---
    lines.append("## 3. Per-Strategy Breakdown")
    if not strategy_breakdown:
        lines.append("*No trades.*")
    else:
        lines.append("| Strategy | Trades | Win% | PnL | Avg Trade |")
        lines.append("|----------|--------|------|-----|-----------|")
        for sym, sb in sorted(strategy_breakdown.items()):
            wr = f"{sb['win_rate'] * 100:.0f}%" if sb["win_rate"] is not None else "—"
            lines.append(
                f"| {sym} | {sb['total_trades']} | {wr} "
                f"| {_FMT_MONEY(sb['total_pnl'])} "
                f"| {_FMT_MONEY(sb['avg_trade_pnl'])} |"
            )
    lines.append("")

    # --- 4. Counterfactual ---
    lines.append("## 4. Counterfactual (Signal Regen vs Actual Fills)")
    if not counterfactual:
        lines.append("*Counterfactual skipped (no bar data or import error).*")
    else:
        for sym, events in counterfactual.items():
            lines.append(f"### {sym}")
            if not events:
                lines.append("*No signals generated by strategy today.*")
                continue
            for ev in events:
                ev_type = ev.get("type", "")
                if ev_type == "missed_entry":
                    lines.append(
                        f"- **MISSED ENTRY** @ {ev.get('bar_time', '?')} "
                        f"price={ev.get('signal_price', '?'):.2f}"
                    )
                elif ev_type == "expected_trade":
                    lines.append(
                        f"- executed as expected @ {ev.get('bar_time', '?')} "
                        f"signal_price={ev.get('signal_price', '?'):.2f}"
                    )
                else:
                    lines.append(f"- {ev_type}: {ev.get('note', '')}")
    lines.append("")

    # --- 5. Mistake taxonomy ---
    lines.append("## 5. Mistake Taxonomy")
    if not taxonomy:
        lines.append("*No losing trades — nothing to classify.*")
    else:
        lines.append("| Symbol | Entry Time | PnL | Slippage Ticks | Cause |")
        lines.append("|--------|------------|-----|---------------|-------|")
        for row in taxonomy:
            lines.append(
                f"| {row['symbol']} | {row['entry_time'][:16]} "
                f"| {_FMT_MONEY(row['pnl'])} | {row['slippage_ticks']} "
                f"| **{row['cause']}** |"
            )
    lines.append("")

    # --- 6. Tomorrow's outlook ---
    lines.append("## 6. Tomorrow's Outlook")
    if not outlook:
        lines.append("*Outlook unavailable.*")
    else:
        for sym, desc in sorted(outlook.items()):
            lines.append(f"- **{sym}**: {desc}")
    lines.append("")
    lines.append("---")
    lines.append("*JARVIS post-trade report — paper trading validation period*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discord posting
# ---------------------------------------------------------------------------


async def _post_to_discord(report_date: date, metrics: dict[str, Any], report_path: Path) -> None:
    """Post a brief Discord headline using the existing discord_eod_summary helper."""
    try:
        from notifications.discord_notifier import discord_eod_summary  # noqa: E402
    except ImportError:
        logger.warning("discord_notifier not importable — Discord post skipped")
        return

    m = metrics
    wins = m["wins"]
    losses = m["losses"]
    total = m["total_trades"]
    daily_pnl = m["total_pnl"]
    best = m.get("biggest_win") or 0.0
    worst = m.get("biggest_loss") or 0.0

    await discord_eod_summary(
        total_trades=total,
        wins=wins,
        losses=losses,
        daily_pnl=daily_pnl,
        best_trade_pnl=best,
        worst_trade_pnl=worst,
        regime_state=f"report saved → {report_path.name}",
    )
    logger.info("Discord eod_summary posted for %s", report_date)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS daily post-trade report")
    parser.add_argument(
        "--date",
        default=None,
        help="Target date YYYY-MM-DD (default: today ET)",
    )
    parser.add_argument(
        "--no-discord",
        action="store_true",
        help="Skip Discord post (enabled by default)",
    )
    args = parser.parse_args()

    if args.date:
        try:
            report_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error("Invalid --date '%s'. Use YYYY-MM-DD.", args.date)
            sys.exit(1)
    else:
        report_date = datetime.now(_ET).date()

    logger.info("Generating post-trade report for %s", report_date)

    # Load + filter trades
    raw = load_trades_json()
    day_raw = filter_trades_to_date(raw, report_date)
    trades = _pair_trades(day_raw)
    logger.info("Found %d raw entries → %d closed round-trips", len(day_raw), len(trades))

    # Compute all sections
    metrics = compute_metrics(trades)
    strategy_breakdown = compute_strategy_breakdown(trades)
    counterfactual = compute_counterfactual(trades, report_date)
    taxonomy = compute_mistake_taxonomy(trades)
    outlook = compute_outlook(report_date)

    # Render
    report_md = render_report(
        report_date=report_date,
        trades=trades,
        metrics=metrics,
        strategy_breakdown=strategy_breakdown,
        counterfactual=counterfactual,
        taxonomy=taxonomy,
        outlook=outlook,
    )

    # Save
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _REPORT_DIR / f"{report_date.isoformat()}.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.info("Report saved → %s", report_path)

    # Discord
    if not args.no_discord:
        try:
            asyncio.run(_post_to_discord(report_date, metrics, report_path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Discord post failed: %s", exc)
    else:
        logger.info("Discord post skipped (--no-discord)")

    # Print headline to stdout for cron log capture
    m = metrics
    pnl_str = _FMT_MONEY(m["total_pnl"])
    wr_str = _FMT_PCT(m["win_rate"] * 100 if m["win_rate"] is not None else None)
    print(
        f"[JARVIS] {report_date} | trades={m['total_trades']} wins={m['wins']} "
        f"losses={m['losses']} win_rate={wr_str} pnl={pnl_str} "
        f"goal={m['goal_progress_pct']:.1f}%"
    )


if __name__ == "__main__":
    main()
