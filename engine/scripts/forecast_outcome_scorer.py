"""
Evening outcome scorer for the self-improving morning briefing (Phase D).

Grades the most recent COMPLETED session by default (the prior trading day), so
the daily bar is final rather than a partial pre-settlement bar. For each
(date, symbol) row written by the morning brief
(Phase A levels + Phase B JARVIS's Read), it pulls the actual session OHLC,
grades the structural levels and the Read, writes the outcome back to the
forecast journal, emits a markdown report, and posts a one-line scoreline to
Discord. This is what makes the brief *self-improving*: the calibrator (Phase E)
reads these graded rows to tune tomorrow.

Read grading mirrors engine/analytics/ic_ensemble.py::BrierCalibrationTracker:

    confidence = conviction                         in [0, 1]
    correct    = 1 if sign(bias) == sign(close-open) else 0
    brier      = (confidence - correct)^2           in [0, 1]   (lower = better)

A neutral read is "no opinion" -> not scored (read_score/read_brier left NULL),
the same way the tracker excludes zero-magnitude signals.

Display/journal only — nothing here is consumed by risk/ or order execution.

Usage
-----
    python -m engine.scripts.forecast_outcome_scorer                # today ET
    python -m engine.scripts.forecast_outcome_scorer --date 2026-06-24
    python -m engine.scripts.forecast_outcome_scorer --no-discord
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("forecast_outcome_scorer")

# Path bootstrap — same pattern as the other scripts in this directory.
_SCRIPTS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPTS_DIR.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

_ET = ZoneInfo("America/New_York")
_UTC = timezone.utc

_DB_PATH = _ENGINE_DIR / "data" / "jarvis_trader.db"
_REPORT_DIR = _ENGINE_DIR / "data" / "forecast_reports"

# Same instrument set + 1h lookback as the morning brief's level engine.
_LEVELS_SYMBOLS: tuple[str, ...] = ("MES", "MNQ", "MGC")
_LEVELS_LABELS: dict[str, str] = {"MES": "ES (via MES)", "MNQ": "NQ (via MNQ)", "MGC": "MGC"}
_LOOKBACK_1H = 1200
_READ_ANCHOR = "MES"

_BIAS_SIGN = {"bullish": 1, "bearish": -1, "neutral": 0}


# ---------------------------------------------------------------------------
# Actual OHLC
# ---------------------------------------------------------------------------


def fetch_actual_ohlc(
    symbol: str, target_date: date, db_path: Path | None = None
) -> Optional[dict[str, float]]:
    """Return the actual daily OHLC for ``symbol`` on ``target_date``, or None.

    Reuses the same 1h-bars -> daily-resample path as the morning level engine so
    the graded session matches the forecast's basis exactly.
    """
    try:
        from analysis.morning_levels import resample_ohlc_to_daily
        from analytics.regime import load_recent_bars
    except ImportError as exc:  # pragma: no cover - defensive
        logger.warning("actual OHLC unavailable — import failed: %s", exc)
        return None

    df1h = load_recent_bars(symbol, n_bars=_LOOKBACK_1H, db_path=db_path or _DB_PATH)
    if df1h is None or len(df1h) == 0:
        return None
    daily = resample_ohlc_to_daily(df1h)
    if daily is None or len(daily) == 0:
        return None
    match = daily[daily.index.date == target_date]
    if len(match) == 0:
        return None
    row = match.iloc[-1]
    try:
        return {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Grading (pure)
# ---------------------------------------------------------------------------


def _touched(level: Any, low: float, high: float) -> bool:
    try:
        lv = float(level)
    except (TypeError, ValueError):
        return False
    return low <= lv <= high


def grade_levels(levels: dict[str, Any] | None, actual: dict[str, float]) -> dict[str, Any]:
    """Grade the structural levels against the realized session. Pure.

    Returns a dict with: which pivot/triggers were touched, count of up/down
    targets reached, realized-range vs ATR, and a touched-fraction summary.
    """
    if not levels:
        return {"graded": False, "reason": "no levels"}

    low = actual["low"]
    high = actual["high"]
    close = actual["close"]
    rng = high - low

    pivot_levels = {
        k: levels.get(k) for k in ("pivot", "r1", "s1", "r2", "s2") if levels.get(k) is not None
    }
    touched = {k: _touched(v, low, high) for k, v in pivot_levels.items()}

    ups = [t for t in (levels.get("targets_up") or []) if t is not None]
    downs = [t for t in (levels.get("targets_down") or []) if t is not None]
    up_hits = sum(1 for t in ups if high >= float(t))
    down_hits = sum(1 for t in downs if low <= float(t))

    atr = levels.get("atr")
    range_vs_atr = None
    if atr:
        try:
            range_vs_atr = round(rng / float(atr), 3)
        except (TypeError, ValueError, ZeroDivisionError):
            range_vs_atr = None

    n_touch = sum(1 for v in touched.values() if v)
    n_total = len(touched) if touched else 0
    touch_frac = round(n_touch / n_total, 3) if n_total else None

    pivot = levels.get("pivot")
    close_vs_pivot = None
    if pivot is not None:
        close_vs_pivot = "above" if close >= float(pivot) else "below"

    return {
        "graded": True,
        "touched": touched,
        "touch_fraction": touch_frac,
        "up_targets_hit": up_hits,
        "up_targets_total": len(ups),
        "down_targets_hit": down_hits,
        "down_targets_total": len(downs),
        "range_vs_atr": range_vs_atr,
        "close_vs_pivot": close_vs_pivot,
    }


def grade_read(
    read: dict[str, Any] | None, actual: dict[str, float]
) -> tuple[Optional[float], Optional[float]]:
    """Grade JARVIS's Read. Returns (read_score, read_brier).

    read_score = 1.0 correct / 0.0 wrong / 0.5 flat session.
    read_brier = (conviction - correct)^2.
    Neutral or absent read -> (None, None): no opinion, not scored.
    """
    if not read:
        return None, None
    bias = str(read.get("bias", "neutral")).lower()
    sign = _BIAS_SIGN.get(bias, 0)
    if sign == 0:
        return None, None  # no directional opinion

    move = actual["close"] - actual["open"]
    if move == 0:
        correct = 0.5
    else:
        correct = 1.0 if (move > 0) == (sign > 0) else 0.0

    try:
        conviction = float(read.get("conviction", 0.0) or 0.0)
    except (TypeError, ValueError):
        conviction = 0.0
    conviction = max(0.0, min(1.0, conviction))
    brier = round((conviction - correct) ** 2, 4)
    return correct, brier


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def score_date(
    target_date: date,
    symbols: tuple[str, ...] = _LEVELS_SYMBOLS,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Grade every journal row for ``target_date`` and persist outcomes."""
    try:
        from analysis.forecast_journal import get_forecast, update_outcome
    except ImportError as exc:  # pragma: no cover - defensive
        logger.warning("forecast journal unavailable: %s", exc)
        return []

    date_str = target_date.isoformat()
    ts = datetime.now(_UTC).isoformat()
    results: list[dict[str, Any]] = []

    for sym in symbols:
        fc = get_forecast(date_str, sym, db_path=db_path or _DB_PATH)
        if fc is None:
            continue
        actual = fetch_actual_ohlc(sym, target_date, db_path=db_path or _DB_PATH)
        if actual is None:
            results.append({"symbol": sym, "graded": False, "reason": "no actual OHLC"})
            continue

        level_scores = grade_levels(fc.get("levels"), actual)
        read_score, read_brier = (None, None)
        if sym == _READ_ANCHOR and fc.get("read"):
            read_score, read_brier = grade_read(fc.get("read"), actual)

        update_outcome(
            date_str,
            sym,
            actual,
            ts,
            level_scores=level_scores,
            read_score=read_score,
            read_brier=read_brier,
            db_path=db_path or _DB_PATH,
        )
        results.append(
            {
                "symbol": sym,
                "graded": True,
                "actual": actual,
                "level_scores": level_scores,
                "read": fc.get("read"),
                "read_score": read_score,
                "read_brier": read_brier,
            }
        )

    return results


def render_report(target_date: date, results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append(f"# JARVIS Forecast Scorecard — {target_date.isoformat()}")
    now_et = datetime.now(_ET).strftime("%Y-%m-%dT%H:%M %Z")
    lines.append(f"*Scored {now_et}. Grades the morning forecast against the realized session.*")
    lines.append("")

    graded = [r for r in results if r.get("graded")]
    if not graded:
        lines.append("*No graded rows — no forecast journal entries or no actual OHLC available.*")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Levels vs Actual")
    lines.append("| Instrument | O / H / L / C | Touched | Up tgts | Down tgts | Range/ATR |")
    lines.append("|---|---|---|---|---|---|")
    for r in graded:
        sym = r["symbol"]
        label = _LEVELS_LABELS.get(sym, sym)
        a = r["actual"]
        ls = r["level_scores"]
        ohlc = f"{a['open']:.2f} / {a['high']:.2f} / {a['low']:.2f} / {a['close']:.2f}"
        touch = ls.get("touch_fraction")
        touch_str = f"{touch:.0%}" if touch is not None else "—"
        up = f"{ls.get('up_targets_hit', 0)}/{ls.get('up_targets_total', 0)}"
        down = f"{ls.get('down_targets_hit', 0)}/{ls.get('down_targets_total', 0)}"
        rva = ls.get("range_vs_atr")
        rva_str = f"{rva:.2f}x" if rva is not None else "—"
        lines.append(f"| {label} | {ohlc} | {touch_str} | {up} | {down} | {rva_str} |")
    lines.append("")

    # JARVIS's Read grade (anchor symbol).
    anchor = next((r for r in graded if r["symbol"] == _READ_ANCHOR and r.get("read")), None)
    lines.append("## JARVIS's Read — Graded")
    if anchor is None or anchor.get("read_score") is None:
        lines.append("*No directional read to score (neutral or absent).*")
        lines.append("")
    else:
        read = anchor["read"]
        bias = str(read.get("bias", "?")).upper()
        conv = float(read.get("conviction", 0.0) or 0.0)
        score = anchor["read_score"]
        brier = anchor["read_brier"]
        verdict = "CORRECT" if score and score >= 1.0 else ("FLAT" if score == 0.5 else "WRONG")
        lines.append(f"- **Call:** {bias} @ {round(conv * 10)}/10 conviction")
        lines.append(
            f"- **Outcome:** {verdict} (score {score:.1f}, Brier {brier:.3f} — lower better)"
        )
        lines.append("")

    lines.append("---")
    lines.append("*JARVIS forecast scorecard — self-improving briefing loop*")
    return "\n".join(lines)


def _scoreline(target_date: date, results: list[dict[str, Any]]) -> str:
    graded = [r for r in results if r.get("graded")]
    anchor = next(
        (r for r in graded if r["symbol"] == _READ_ANCHOR and r.get("read_score") is not None), None
    )
    if anchor is not None:
        bias = str(anchor["read"].get("bias", "?")).upper()
        score = anchor["read_score"]
        verdict = "CORRECT" if score >= 1.0 else ("FLAT" if score == 0.5 else "WRONG")
        read_part = f"read={bias} {verdict} (Brier {anchor['read_brier']:.3f})"
    else:
        read_part = "read=none"
    return f"[JARVIS SCORECARD] {target_date} | graded={len(graded)} | {read_part}"


async def _post_scoreline(
    target_date: date, results: list[dict[str, Any]], report_path: Path
) -> None:
    try:
        import httpx  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("httpx not available — Discord post skipped")
        return
    webhook_url = (os.getenv("DISCORD_WEBHOOK_URL") or "").strip()
    if not webhook_url:
        logger.info("DISCORD_WEBHOOK_URL not set — Discord post skipped")
        return
    content = _scoreline(target_date, results) + f" | report={report_path.name}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json={"content": content, "username": "JARVIS"})
            if resp.status_code in (200, 204):
                logger.info("Discord scoreline posted for %s", target_date)
            else:
                logger.warning("Discord webhook returned %s", resp.status_code)
    except Exception as exc:
        logger.warning("Discord scoreline post failed: %s", exc)


def _default_score_date(db_path: Path | None = None) -> date:
    """Most recent forecast date strictly before today ET — the last session whose
    daily bar is complete.

    Grading "today" at the 4:15pm slot would use a partial, pre-settlement bar
    (futures settle ~5pm ET and the resampled daily bar is still forming), so the
    Read would be scored against an intraday price rather than the real close.
    Grading the prior completed session avoids that. Falls back to yesterday when
    the journal is empty.
    """
    today = datetime.now(_ET).date()
    try:
        from analysis.forecast_journal import list_journal

        rows = list_journal(db_path=db_path or _DB_PATH)
        prior = [
            date.fromisoformat(r["date"])
            for r in rows
            if r.get("date") and date.fromisoformat(r["date"]) < today
        ]
        if prior:
            return max(prior)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("default score-date lookup failed: %s", exc)
    return today - timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS forecast outcome scorer")
    parser.add_argument(
        "--date",
        default=None,
        help="Target date YYYY-MM-DD (default: most recent completed session)",
    )
    parser.add_argument("--no-discord", action="store_true", help="Skip Discord scoreline post")
    args = parser.parse_args()

    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error("Invalid --date '%s'. Use YYYY-MM-DD.", args.date)
            sys.exit(1)
    else:
        target_date = _default_score_date()

    logger.info("Scoring forecast for %s", target_date)
    results = score_date(target_date)

    report_md = render_report(target_date, results)
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _REPORT_DIR / f"{target_date.isoformat()}.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.info("Scorecard saved -> %s", report_path)

    if not args.no_discord:
        import asyncio

        asyncio.run(_post_scoreline(target_date, results, report_path))
    else:
        logger.info("Discord post skipped (--no-discord)")

    print(_scoreline(target_date, results))


if __name__ == "__main__":
    main()
