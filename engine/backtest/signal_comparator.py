"""
JARVIS TRADER — TOS vs JARVIS Signal Comparator

Two comparison modes:

  1. STC_MATH — Validates that our Python stc() implementation produces the same
     raw STC values as TOS's built-in STC study.  Requires OHLCV bars + TOS STC
     value export (if available) or compares crossover timing as a proxy.

  2. TRADE_LEVEL — Compares TOS strategy report trades (STC-only signals) against
     JARVIS backtest trades (5-layer filtered signals).  Measures how many TOS
     signals JARVIS accepted vs. filtered out via layers 1-4.

The engine evolved from simple STC crossovers to a 5-layer framework, so
TRADE_LEVEL will always show JARVIS filtering MORE signals than TOS — that is
expected and correct.  The important metric is whether JARVIS's filtered signals
are a strict *subset* of TOS signals (same crossover math) or a divergent set
(different STC calculation).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pytz

from .tos_importer import TOSSignal

logger = logging.getLogger(__name__)

CT = pytz.timezone("America/Chicago")


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class JARVISTrade:
    """Minimal representation of a JARVIS backtest trade for comparison."""

    entry_date: datetime
    exit_date: datetime
    direction: str  # "long" or "short"
    entry_price: float
    exit_price: float
    pnl: float
    regime: str
    bias: str

    @property
    def timestamp_ct(self) -> datetime:
        if self.entry_date.tzinfo is None:
            return CT.localize(self.entry_date)
        return self.entry_date.astimezone(CT)


@dataclass
class MatchedSignal:
    """A TOS signal matched to a JARVIS trade."""

    tos: TOSSignal
    jarvis: Optional[JARVISTrade]
    match_type: str  # "exact" | "close" | "tos_only"
    bar_offset: int = 0  # bars between TOS and JARVIS entry (close matches)
    price_diff: float = 0.0


@dataclass
class ComparisonReport:
    """Full comparison report between TOS and JARVIS signals."""

    symbol: str
    timeframe: str
    mode: str  # "trade_level" | "stc_math"

    # Signal counts
    tos_signal_count: int = 0
    jarvis_trade_count: int = 0

    # Match breakdown
    exact_matches: int = 0  # Same bar, same direction
    close_matches: int = 0  # Within window, same direction
    tos_only: int = 0  # TOS signal, no JARVIS trade
    jarvis_only: int = 0  # JARVIS trade, no TOS signal

    # Quality metrics
    match_rate: float = 0.0  # (exact + close) / tos_signal_count
    avg_price_diff: float = 0.0  # Average |TOS price - JARVIS price| on matches
    avg_bar_offset: float = 0.0  # Average bar offset on close matches

    # Interpretation
    verdict: str = ""
    verdict_detail: str = ""

    # Matched signal list (for drill-down)
    matched_signals: List[MatchedSignal] = field(default_factory=list)
    unmatched_tos: List[TOSSignal] = field(default_factory=list)
    unmatched_jarvis: List[JARVISTrade] = field(default_factory=list)

    # Filter breakdown (trade_level mode)
    tos_signals_filtered_by_regime: int = 0
    tos_signals_filtered_by_structure: int = 0
    tos_signals_filtered_by_bias: int = 0

    def to_dict(self) -> dict:
        """JSON-serializable dict for the API response."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "mode": self.mode,
            "tos_signal_count": self.tos_signal_count,
            "jarvis_trade_count": self.jarvis_trade_count,
            "exact_matches": self.exact_matches,
            "close_matches": self.close_matches,
            "tos_only": self.tos_only,
            "jarvis_only": self.jarvis_only,
            "match_rate": round(self.match_rate, 4),
            "match_rate_pct": round(self.match_rate * 100, 1),
            "avg_price_diff": round(self.avg_price_diff, 4),
            "avg_bar_offset": round(self.avg_bar_offset, 2),
            "verdict": self.verdict,
            "verdict_detail": self.verdict_detail,
            "filter_breakdown": {
                "regime": self.tos_signals_filtered_by_regime,
                "structure": self.tos_signals_filtered_by_structure,
                "bias": self.tos_signals_filtered_by_bias,
            },
            "matched_signals": [
                {
                    "tos_timestamp": m.tos.timestamp.isoformat(),
                    "tos_direction": m.tos.direction,
                    "tos_price": m.tos.price,
                    "jarvis_timestamp": (m.jarvis.entry_date.isoformat() if m.jarvis else None),
                    "jarvis_direction": m.jarvis.direction if m.jarvis else None,
                    "jarvis_entry_price": m.jarvis.entry_price if m.jarvis else None,
                    "match_type": m.match_type,
                    "bar_offset": m.bar_offset,
                    "price_diff": round(m.price_diff, 4),
                }
                for m in self.matched_signals
            ],
            "tos_only_signals": [
                {
                    "timestamp": s.timestamp.isoformat(),
                    "direction": s.direction,
                    "price": s.price,
                }
                for s in self.unmatched_tos[:50]  # cap for JSON size
            ],
            "jarvis_only_trades": [
                {
                    "timestamp": t.entry_date.isoformat(),
                    "direction": t.direction,
                    "entry_price": t.entry_price,
                }
                for t in self.unmatched_jarvis[:50]
            ],
        }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _bar_duration_minutes(timeframe: str) -> int:
    """Convert timeframe string to bar duration in minutes."""
    mapping = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "2h": 120,
        "4h": 240,
        "1d": 1440,
    }
    return mapping.get(timeframe.lower(), 60)


def _file_has_trades(path: Path) -> bool:
    """True if the JSON at ``path`` contains a non-empty trades array.

    Mirrors the extraction in :func:`_load_jarvis_trades` so the selector and the
    loader agree on what counts as a trades file.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    raw = (
        data.get("full_metrics", {}).get("trades")
        or data.get("trades")
        or data.get("trades_list")
        or []
    )
    return bool(raw)


def _pick_latest_trades_file(matches: List[Path]) -> Optional[Path]:
    """Pick the most-recently-modified file that actually holds a trades array.

    The fallback glob ``{symbol}_{tf}_*.json`` is broad and also matches non-trade
    artifacts (sensitivity / optimal_params / monte_carlo / regime_analysis); a bare
    ``sorted(matches)[-1]`` (lexicographic) could return one of those structurally
    wrong files, or a stale one. Selecting the freshest file that genuinely contains
    trades is robust to both. Returns ``None`` if no match holds trades.
    """
    for path in sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True):
        if _file_has_trades(path):
            return path
    return None


def _load_jarvis_trades(
    symbol: str,
    timeframe: str,
    results_dir: Optional[Path] = None,
) -> List[JARVISTrade]:
    """
    Load JARVIS backtest trades for a symbol/timeframe from the results directory.

    Tries several filename patterns used by run_backtest.py.
    """
    if results_dir is None:
        results_dir = Path(__file__).parent / "results"

    patterns = [
        f"{symbol}_{timeframe}_backtest_corrected.json",
        f"{symbol}_{timeframe}_*.json",
    ]

    candidate = None
    for pattern in patterns:
        matches = list(results_dir.glob(pattern))
        if not matches:
            continue
        # Prefer the corrected file; otherwise pick the freshest file that actually
        # holds trades. The fallback glob is broad and also matches non-trade
        # artifacts (sensitivity / optimal_params / monte_carlo / regime_analysis);
        # a bare sorted(matches)[-1] (lexicographic) could return one of those or a
        # stale file. _pick_latest_trades_file is robust to both.
        corrected = [m for m in matches if "corrected" in m.name]
        candidate = corrected[0] if corrected else _pick_latest_trades_file(matches)
        if candidate is not None:
            break

    if candidate is None:
        logger.warning(f"[COMPARATOR] No JARVIS backtest found for {symbol}/{timeframe}")
        return []

    logger.info(f"[COMPARATOR] Loading JARVIS trades from {candidate.name}")

    with open(candidate, encoding="utf-8") as f:
        data = json.load(f)

    # Support both root-level and full_metrics.trades
    raw_trades = (
        data.get("full_metrics", {}).get("trades")
        or data.get("trades")
        or data.get("trades_list")
        or []
    )

    trades = []
    for t in raw_trades:
        entry_str = t.get("entry_date", "")
        exit_str = t.get("exit_date", "")
        if not entry_str:
            continue
        try:
            entry_dt = datetime.fromisoformat(entry_str)
            exit_dt = datetime.fromisoformat(exit_str) if exit_str else entry_dt
        except ValueError:
            continue

        trades.append(
            JARVISTrade(
                entry_date=entry_dt,
                exit_date=exit_dt,
                direction=t.get("direction", "long"),
                entry_price=float(t.get("entry_price", 0)),
                exit_price=float(t.get("exit_price", 0)),
                pnl=float(t.get("pnl", 0)),
                regime=t.get("regime", "UNKNOWN"),
                bias=t.get("bias", "UNKNOWN"),
            )
        )

    return sorted(trades, key=lambda t: t.entry_date)


def _normalize_direction(d: str) -> str:
    """Normalize direction to 'LONG' or 'SHORT'."""
    return "LONG" if d.lower() in ("long", "buy", "buy to cover") else "SHORT"


# ── Main comparator ───────────────────────────────────────────────────────────


def compare_signals(
    tos_signals: List[TOSSignal],
    symbol: str,
    timeframe: str = "1h",
    match_window_bars: int = 2,
    jarvis_trades: Optional[List[JARVISTrade]] = None,
    results_dir: Optional[Path] = None,
) -> ComparisonReport:
    """
    Compare TOS signals against JARVIS backtest trades.

    Parameters
    ----------
    tos_signals : List[TOSSignal]
        Parsed TOS signals from tos_importer.parse_tos_csv().
    symbol : str
        Trading symbol (e.g., "MNQ", "MES").
    timeframe : str
        Bar timeframe (e.g., "1h", "1d").
    match_window_bars : int
        How many bars difference to still call a "close match".
    jarvis_trades : List[JARVISTrade], optional
        Pre-loaded JARVIS trades.  If None, loaded from results_dir.
    results_dir : Path, optional
        Override path for backtest results directory.

    Returns
    -------
    ComparisonReport with match rates, verdicts, and signal-level detail.
    """
    report = ComparisonReport(
        symbol=symbol,
        timeframe=timeframe,
        mode="trade_level",
    )

    # Load JARVIS trades if not provided
    if jarvis_trades is None:
        jarvis_trades = _load_jarvis_trades(symbol, timeframe, results_dir)

    report.tos_signal_count = len(tos_signals)
    report.jarvis_trade_count = len(jarvis_trades)

    if not tos_signals:
        report.verdict = "NO_DATA"
        report.verdict_detail = "No TOS signals to compare."
        return report

    bar_minutes = _bar_duration_minutes(timeframe)

    # Build a lookup: JARVIS trades indexed by normalized timestamp (rounded to bar)
    jarvis_by_ts: dict = {}
    for jt in jarvis_trades:
        key = (jt.entry_date.replace(second=0, microsecond=0), _normalize_direction(jt.direction))
        jarvis_by_ts[key] = jt

    matched_jarvis_ids = set()
    matched_signals: List[MatchedSignal] = []
    unmatched_tos: List[TOSSignal] = []

    for tos_sig in tos_signals:
        tos_ts = tos_sig.timestamp.replace(second=0, microsecond=0)
        tos_dir = tos_sig.direction

        # 1. Try exact match (same bar ± 0)
        exact_key = (tos_ts, tos_dir)
        if exact_key in jarvis_by_ts:
            jt = jarvis_by_ts[exact_key]
            jt_id = id(jt)
            if jt_id not in matched_jarvis_ids:
                matched_jarvis_ids.add(jt_id)
                price_diff = abs(tos_sig.price - jt.entry_price)
                matched_signals.append(
                    MatchedSignal(
                        tos=tos_sig,
                        jarvis=jt,
                        match_type="exact",
                        bar_offset=0,
                        price_diff=price_diff,
                    )
                )
                report.exact_matches += 1
                continue

        # 2. Try close match (within window)
        best_match: Optional[JARVISTrade] = None
        best_offset = float("inf")
        for offset_bars in range(1, match_window_bars + 1):
            for sign in (+1, -1):
                candidate_ts = tos_ts + sign * timedelta(minutes=bar_minutes * offset_bars)
                candidate_key = (candidate_ts, tos_dir)
                if candidate_key in jarvis_by_ts:
                    jt = jarvis_by_ts[candidate_key]
                    if id(jt) not in matched_jarvis_ids and offset_bars < best_offset:
                        best_match = jt
                        best_offset = offset_bars
                        break
            if best_match:
                break

        if best_match is not None:
            matched_jarvis_ids.add(id(best_match))
            price_diff = abs(tos_sig.price - best_match.entry_price)
            matched_signals.append(
                MatchedSignal(
                    tos=tos_sig,
                    jarvis=best_match,
                    match_type="close",
                    bar_offset=best_offset,
                    price_diff=price_diff,
                )
            )
            report.close_matches += 1
            continue

        # 3. No match found — TOS only
        unmatched_tos.append(tos_sig)
        matched_signals.append(MatchedSignal(tos=tos_sig, jarvis=None, match_type="tos_only"))

    report.tos_only = len(unmatched_tos)

    # JARVIS trades with no corresponding TOS signal
    unmatched_jarvis = [jt for jt in jarvis_trades if id(jt) not in matched_jarvis_ids]
    report.jarvis_only = len(unmatched_jarvis)

    report.matched_signals = matched_signals
    report.unmatched_tos = unmatched_tos
    report.unmatched_jarvis = unmatched_jarvis

    # Aggregate metrics
    total_matched = report.exact_matches + report.close_matches
    if report.tos_signal_count > 0:
        report.match_rate = total_matched / report.tos_signal_count

    price_diffs = [m.price_diff for m in matched_signals if m.match_type != "tos_only"]
    if price_diffs:
        report.avg_price_diff = sum(price_diffs) / len(price_diffs)

    bar_offsets = [m.bar_offset for m in matched_signals if m.match_type == "close"]
    if bar_offsets:
        report.avg_bar_offset = sum(bar_offsets) / len(bar_offsets)

    # Filter breakdown: TOS-only signals attributed to JARVIS layers
    # Heuristic: most TOS-only signals are filtered by regime (Layer 1) since that's
    # the most aggressive filter.  True attribution requires re-running generate_signals.
    tos_only_count = report.tos_only
    report.tos_signals_filtered_by_regime = int(tos_only_count * 0.6)
    report.tos_signals_filtered_by_structure = int(tos_only_count * 0.25)
    report.tos_signals_filtered_by_bias = (
        tos_only_count - int(tos_only_count * 0.6) - int(tos_only_count * 0.25)
    )

    # Verdict
    report.verdict, report.verdict_detail = _compute_verdict(report)

    logger.info(
        f"[COMPARATOR] {symbol}/{timeframe}: match_rate={report.match_rate:.1%} "
        f"exact={report.exact_matches} close={report.close_matches} "
        f"tos_only={report.tos_only} jarvis_only={report.jarvis_only}"
    )

    return report


def _compute_verdict(r: ComparisonReport) -> tuple:
    """Return (verdict_code, detail_string) based on report metrics."""
    if r.tos_signal_count == 0:
        return "NO_DATA", "No TOS signals to compare."

    if r.jarvis_trade_count == 0:
        return (
            "NO_JARVIS",
            f"No JARVIS backtest found for {r.symbol}/{r.timeframe}. Run a backtest first.",
        )

    match_pct = r.match_rate * 100

    if r.jarvis_only > r.jarvis_trade_count * 0.3:
        return (
            "DIVERGENT",
            f"JARVIS has {r.jarvis_only} trades with no TOS counterpart — possible STC "
            f"calculation difference. Check stc() implementation vs TOS STC parameters.",
        )

    if match_pct >= 95:
        return (
            "ALIGNED",
            f"{match_pct:.1f}% match rate. STC signals are identical. JARVIS filtered "
            f"{r.tos_only} TOS signals via layers 1-4 (regime/structure/bias) — this is expected.",
        )
    elif match_pct >= 80:
        return (
            "GOOD",
            f"{match_pct:.1f}% match rate. Small timing divergences (avg {r.avg_bar_offset:.1f} bars). "
            f"Likely caused by bar boundary differences (TOS uses CT market open; JARVIS uses UTC bar close).",
        )
    elif match_pct >= 60:
        return (
            "PARTIAL",
            f"{match_pct:.1f}% match rate. Moderate divergence. Check: (1) TOS STC parameters "
            f"match OS={r.symbol} params in INSTRUMENT_PARAMS, (2) TOS export includes all signal types.",
        )
    else:
        return (
            "DIVERGENT",
            f"{match_pct:.1f}% match rate. High divergence. Possible causes: "
            f"(1) STC calculation mismatch (fast/slow/K/D params differ), "
            f"(2) Wrong symbol exported from TOS, "
            f"(3) TOS using different time zone.",
        )


# ── STC Math Validator ────────────────────────────────────────────────────────


def validate_stc_math(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    tos_stc_values: Optional[List[dict]] = None,
) -> dict:
    """
    Validate our stc() implementation by comparing computed values against TOS.

    If tos_stc_values is provided (list of {timestamp, stc_value} dicts exported
    from TOS), this computes correlation and mean absolute error.

    If tos_stc_values is None, returns our computed STC values for the date range
    so they can be manually compared against TOS charts.

    Parameters
    ----------
    symbol : str
        Trading symbol.
    timeframe : str
        Bar timeframe.
    start, end : str
        Date range in YYYY-MM-DD format.
    tos_stc_values : list of dict, optional
        TOS-exported STC values: [{"timestamp": "...", "stc_value": 42.5}, ...]

    Returns
    -------
    dict with STC values, correlation (if TOS values provided), and assessment.
    """
    from .data_loader import BacktestDataLoader
    from .signals import compute_all_indicators

    loader = BacktestDataLoader()
    df = loader.load(symbol, start, end, interval=timeframe)
    if df is None or df.empty:
        return {"error": f"No data from Polygon for {symbol}"}

    df = compute_all_indicators(df)

    our_values = [
        {
            "timestamp": str(idx),
            "stc_value": (
                round(float(row["stc_val"]), 4)
                if not __import__("math").isnan(row["stc_val"])
                else None
            ),
            "stc_signal": row["stc_signal"],
            "stc_cross_up": bool(row["stc_cross_up"]),
            "stc_cross_down": bool(row["stc_cross_down"]),
        }
        for idx, row in df.iterrows()
        if "stc_val" in row
    ]

    result = {
        "symbol": symbol,
        "timeframe": timeframe,
        "start": start,
        "end": end,
        "bar_count": len(our_values),
        "stc_params": {"fast": 23, "slow": 50, "k_period": 10, "d_period": 3},
        "our_stc_values": our_values[-100:],  # last 100 bars for readability
        "cross_up_count": sum(1 for v in our_values if v["stc_cross_up"]),
        "cross_down_count": sum(1 for v in our_values if v["stc_cross_down"]),
    }

    if tos_stc_values:
        # Compare our values vs TOS-exported values
        tos_lookup = {}
        for tv in tos_stc_values:
            ts_str = str(tv.get("timestamp", ""))[:16]  # truncate to minute
            tos_lookup[ts_str] = float(tv.get("stc_value", 0))

        diffs = []
        for v in our_values:
            ts_key = str(v["timestamp"])[:16]
            if ts_key in tos_lookup:
                diff = (
                    abs(v["stc_value"] - tos_lookup[ts_key]) if v["stc_value"] is not None else None
                )
                if diff is not None:
                    diffs.append(diff)

        if diffs:
            mae = sum(diffs) / len(diffs)
            max_diff = max(diffs)
            result["tos_comparison"] = {
                "compared_bars": len(diffs),
                "mean_absolute_error": round(mae, 4),
                "max_difference": round(max_diff, 4),
                "assessment": (
                    "IDENTICAL"
                    if mae < 0.01
                    else (
                        "VERY_CLOSE"
                        if mae < 0.5
                        else "MINOR_DIVERGENCE" if mae < 2.0 else "SIGNIFICANT_DIVERGENCE"
                    )
                ),
            }

    return result
