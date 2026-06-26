"""
Morning-forecast calibrator (Phase E) — the "gets better daily" loop.

Reads N days of graded rows from the forecast journal (Phase C/D) and produces:
  - read calibration: directional hit-rate + mean Brier per conviction tier,
    an overconfidence flag, and a suggested conviction-shrink factor;
  - level stats: per-level touch rates and target-ladder hit rates;
  - a state JSON consumed by JARVIS's Read (Phase B) to self-correct, plus a
    human-readable calibration report.

Mirrors engine/analytics/gate_v2_calibrator.py (collect -> summarize ->
diff/recommend -> render + persist). Recommendations are surfaced, not silently
applied: level geometry is never auto-mutated, and the only feedback wired into
generation is a textual calibration hint + an honest conviction-shrink factor.

Display/journal only — nothing here is consumed by risk/ or order execution.

Usage
-----
    python -m engine.analytics.morning_levels_calibrator               # last 30d
    python -m engine.analytics.morning_levels_calibrator --days 60
    python -m engine.analytics.morning_levels_calibrator --date 2026-06-25
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("morning_levels_calibrator")

_ANALYTICS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _ANALYTICS_DIR.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

_DB_PATH = _ENGINE_DIR / "data" / "jarvis_trader.db"
_STATE_PATH = _ENGINE_DIR / "data" / "morning_levels_calibrator_state.json"
_REPORT_DIR = _ENGINE_DIR / "data" / "forecast_reports"

_DEFAULT_DAYS = 30
_MIN_SAMPLES = 5  # below this, recommendations are advisory-only / muted

# Conviction tiers (lower-inclusive, upper-exclusive except the top).
_TIERS: tuple[tuple[str, float, float], ...] = (
    ("low", 0.0, 0.4),
    ("mid", 0.4, 0.7),
    ("high", 0.7, 1.01),
)
_TIER_MIDPOINT = {"low": 0.25, "mid": 0.55, "high": 0.85}
_PIVOT_KEYS = ("pivot", "r1", "s1", "r2", "s2")


# ---------------------------------------------------------------------------
# Collect
# ---------------------------------------------------------------------------


def collect_graded_rows(
    n_days: int = _DEFAULT_DAYS,
    end_date: date | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Return journal rows in the trailing window that have an outcome (outcome_ts)."""
    try:
        from analysis.forecast_journal import list_journal
    except ImportError as exc:  # pragma: no cover - defensive
        logger.warning("forecast journal unavailable: %s", exc)
        return []
    end = end_date or datetime.now(timezone.utc).date()
    start = end - timedelta(days=n_days)
    rows = list_journal(start.isoformat(), end.isoformat(), db_path=db_path or _DB_PATH)
    return [r for r in rows if r.get("outcome_ts")]


# ---------------------------------------------------------------------------
# Summarize (pure)
# ---------------------------------------------------------------------------


def _tier_for(conviction: float) -> str:
    for name, lo, hi in _TIERS:
        if lo <= conviction < hi:
            return name
    return "high"


def summarize_read_calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Directional hit-rate + mean Brier per conviction tier, overconfidence flag,
    and a suggested conviction-shrink factor in (0, 1]. Pure."""
    scored = [
        r for r in rows if r.get("read_score") is not None and r.get("conviction") is not None
    ]
    tiers: dict[str, dict[str, Any]] = {}
    for name, _lo, _hi in _TIERS:
        tiers[name] = {"n": 0, "hits": 0.0, "brier_sum": 0.0}

    for r in scored:
        conv = float(r["conviction"])
        tier = _tier_for(conv)
        tiers[tier]["n"] += 1
        tiers[tier]["hits"] += float(r["read_score"])
        if r.get("read_brier") is not None:
            tiers[tier]["brier_sum"] += float(r["read_brier"])

    for t in tiers.values():
        n = t["n"]
        t["accuracy"] = round(t["hits"] / n, 3) if n else None
        t["mean_brier"] = round(t["brier_sum"] / n, 4) if n else None
        t.pop("hits", None)
        t.pop("brier_sum", None)

    n_total = len(scored)
    overall_acc = (
        round(sum(float(r["read_score"]) for r in scored) / n_total, 3) if n_total else None
    )

    # Overconfidence: high-tier reads whose realized accuracy lags their claimed
    # confidence midpoint. Shrink factor pulls future conviction toward observed
    # skill. Muted (=1.0, no change) until enough high-tier samples exist.
    high = tiers["high"]
    shrink = 1.0
    overconfident = False
    if high["n"] >= _MIN_SAMPLES and high["accuracy"] is not None:
        claimed = _TIER_MIDPOINT["high"]
        if high["accuracy"] < claimed:
            overconfident = True
            shrink = round(max(0.3, high["accuracy"] / claimed), 3)

    return {
        "n_scored": n_total,
        "overall_accuracy": overall_acc,
        "tiers": tiers,
        "overconfident": overconfident,
        "conviction_shrink": shrink,
    }


def summarize_level_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-level touch rates and target-ladder hit rates across graded rows. Pure."""
    graded = [
        r
        for r in rows
        if isinstance(r.get("level_scores"), dict) and r["level_scores"].get("graded")
    ]
    n = len(graded)
    if n == 0:
        return {"n": 0}

    touch_counts = dict.fromkeys(_PIVOT_KEYS, 0)
    touch_present = dict.fromkeys(_PIVOT_KEYS, 0)
    up_hit = up_tot = down_hit = down_tot = 0
    range_vs_atr_sum = 0.0
    range_vs_atr_n = 0

    for r in graded:
        ls = r["level_scores"]
        touched = ls.get("touched") or {}
        for k in _PIVOT_KEYS:
            if k in touched:
                touch_present[k] += 1
                if touched[k]:
                    touch_counts[k] += 1
        up_hit += int(ls.get("up_targets_hit", 0) or 0)
        up_tot += int(ls.get("up_targets_total", 0) or 0)
        down_hit += int(ls.get("down_targets_hit", 0) or 0)
        down_tot += int(ls.get("down_targets_total", 0) or 0)
        rva = ls.get("range_vs_atr")
        if rva is not None:
            range_vs_atr_sum += float(rva)
            range_vs_atr_n += 1

    touch_rates = {
        k: (round(touch_counts[k] / touch_present[k], 3) if touch_present[k] else None)
        for k in _PIVOT_KEYS
    }
    return {
        "n": n,
        "touch_rates": touch_rates,
        "up_target_hit_rate": round(up_hit / up_tot, 3) if up_tot else None,
        "down_target_hit_rate": round(down_hit / down_tot, 3) if down_tot else None,
        "mean_range_vs_atr": (
            round(range_vs_atr_sum / range_vs_atr_n, 3) if range_vs_atr_n else None
        ),
    }


def _level_recommendations(level_stats: dict[str, Any]) -> list[str]:
    recs: list[str] = []
    n = level_stats.get("n", 0)
    if n < _MIN_SAMPLES:
        recs.append(f"Insufficient graded sessions ({n}) — level recommendations muted.")
        return recs
    up = level_stats.get("up_target_hit_rate")
    down = level_stats.get("down_target_hit_rate")
    for label, rate in (("upside", up), ("downside", down)):
        if rate is None:
            continue
        if rate > 0.8:
            recs.append(f"{label} target ladder hit {rate:.0%} — consider widening ATR multiples.")
        elif rate < 0.2:
            recs.append(
                f"{label} target ladder hit {rate:.0%} — consider tightening ATR multiples."
            )
    mrva = level_stats.get("mean_range_vs_atr")
    if mrva is not None and mrva > 1.5:
        recs.append(f"Realized range averages {mrva:.2f}x ATR — ATR(14) may understate volatility.")
    if not recs:
        recs.append("Level geometry well-calibrated — no change recommended.")
    return recs


def build_state(
    rows: list[dict[str, Any]],
    n_days: int,
    end_date: date,
) -> dict[str, Any]:
    read_cal = summarize_read_calibration(rows)
    level_stats = summarize_level_stats(rows)
    return {
        "as_of": end_date.isoformat(),
        "generated_ts": datetime.now(timezone.utc).isoformat(),
        "n_days": n_days,
        "n_graded_rows": len(rows),
        "read_calibration": read_cal,
        "level_stats": level_stats,
        "level_recommendations": _level_recommendations(level_stats),
    }


# ---------------------------------------------------------------------------
# Persist + render + load
# ---------------------------------------------------------------------------


def write_state(state: dict[str, Any], path: Path | None = None) -> Path:
    out = Path(path or _STATE_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    return out


def load_state(path: Path | None = None) -> Optional[dict[str, Any]]:
    """Load calibrator state for consumption by the Read (Phase B). None if absent."""
    p = Path(path or _STATE_PATH)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def calibration_hint(state: dict[str, Any] | None) -> str:
    """A short natural-language hint for the Read prompt. Empty when no signal."""
    if not state:
        return ""
    rc = state.get("read_calibration") or {}
    n = rc.get("n_scored", 0)
    if n < _MIN_SAMPLES:
        return ""
    parts: list[str] = []
    acc = rc.get("overall_accuracy")
    if acc is not None:
        parts.append(f"Your recent directional reads were correct {acc:.0%} of the time (n={n}).")
    if rc.get("overconfident"):
        parts.append(
            "You have been OVERCONFIDENT on high-conviction calls — be more conservative "
            "with conviction unless the setup is genuinely strong."
        )
    return " ".join(parts)


def render_report(state: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# JARVIS Forecast Calibration — as of {state['as_of']}")
    lines.append(
        f"*Trailing {state['n_days']}d, {state['n_graded_rows']} graded rows. "
        "Self-improvement loop for the morning briefing.*"
    )
    lines.append("")

    rc = state["read_calibration"]
    lines.append("## JARVIS's Read — Calibration")
    if rc["n_scored"] == 0:
        lines.append("*No scored directional reads yet.*")
    else:
        lines.append(
            f"- Overall directional accuracy: **{rc['overall_accuracy']:.0%}** (n={rc['n_scored']})"
        )
        lines.append("")
        lines.append("| Conviction tier | N | Accuracy | Mean Brier |")
        lines.append("|---|---|---|---|")
        for name, _lo, _hi in _TIERS:
            t = rc["tiers"][name]
            acc = f"{t['accuracy']:.0%}" if t["accuracy"] is not None else "—"
            br = f"{t['mean_brier']:.3f}" if t["mean_brier"] is not None else "—"
            lines.append(f"| {name} | {t['n']} | {acc} | {br} |")
        lines.append("")
        if rc["overconfident"]:
            lines.append(
                f"⚠️ **Overconfident** — applying conviction-shrink factor "
                f"**{rc['conviction_shrink']}** to future high-conviction reads."
            )
        else:
            lines.append("Conviction is well-calibrated — no shrink applied.")
    lines.append("")

    ls = state["level_stats"]
    lines.append("## Structural Levels — Calibration")
    if ls.get("n", 0) == 0:
        lines.append("*No graded level rows yet.*")
    else:
        tr = ls["touch_rates"]
        tr_str = ", ".join(f"{k}={tr[k]:.0%}" for k in _PIVOT_KEYS if tr.get(k) is not None)
        lines.append(f"- Pivot/trigger touch rates: {tr_str or '—'}")
        up = ls.get("up_target_hit_rate")
        down = ls.get("down_target_hit_rate")
        lines.append(
            f"- Target ladder hit rate: up {up:.0%} / down {down:.0%}"
            if up is not None and down is not None
            else "- Target ladder hit rate: —"
        )
        if ls.get("mean_range_vs_atr") is not None:
            lines.append(f"- Mean realized range: {ls['mean_range_vs_atr']:.2f}x ATR(14)")
        lines.append("")
        for rec in state["level_recommendations"]:
            lines.append(f"- {rec}")
    lines.append("")
    lines.append("---")
    lines.append(
        "*JARVIS forecast calibrator — recommendations are advisory; level geometry is not auto-mutated.*"
    )
    return "\n".join(lines)


def calibrate(
    n_days: int = _DEFAULT_DAYS,
    end_date: date | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Collect graded rows, build + persist state, return the state dict."""
    end = end_date or datetime.now(timezone.utc).date()
    rows = collect_graded_rows(n_days, end_date=end, db_path=db_path)
    state = build_state(rows, n_days, end)
    write_state(state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS morning-forecast calibrator")
    parser.add_argument("--days", type=int, default=_DEFAULT_DAYS, help="Trailing window (days)")
    parser.add_argument("--date", default=None, help="End date YYYY-MM-DD (default: today UTC)")
    args = parser.parse_args()

    end_date = None
    if args.date:
        try:
            end_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error("Invalid --date '%s'. Use YYYY-MM-DD.", args.date)
            sys.exit(1)

    state = calibrate(args.days, end_date=end_date)
    report = render_report(state)
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _REPORT_DIR / f"calibration_{state['as_of']}.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info("Calibration state -> %s", _STATE_PATH)
    logger.info("Calibration report -> %s", report_path)
    rc = state["read_calibration"]
    print(
        f"[JARVIS CALIBRATION] {state['as_of']} | graded={state['n_graded_rows']} | "
        f"read_acc={rc['overall_accuracy']} | overconfident={rc['overconfident']}"
    )


if __name__ == "__main__":
    main()
