#!/usr/bin/env python
"""
show_verdict_history.py — JARVIS TRADER gate v2 verdict history viewer.

Usage:
    python scripts/show_verdict_history.py
    python scripts/show_verdict_history.py --symbol MNQ
    python scripts/show_verdict_history.py --family breakout
    python scripts/show_verdict_history.py --status FAIL
    python scripts/show_verdict_history.py --no-color

Reads all JSON files under engine/data/gate_v2_verdicts/ and renders a
colour-coded summary table per symbol × family, with trend annotations
(RISING / DECLINING / FLAT) per metric across ranks.

Key feature: _load_json_lenient() handles non-standard JSON tokens
(bare Infinity and NaN) that appear in 6 of the 12 existing verdict files
due to Python's json.dumps(float('inf')) producing 'Infinity' — invalid
per JSON spec but valid in Python eval context.

Trend diagnosis: if all ranks FAIL and pf_ci_lower is DECLINING across 3+
ranks, prints "SIGNAL EXHAUSTED" warning.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ── ANSI colours ─────────────────────────────────────────────────────────────

_RESET = "\033[0m"
_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


def _c(text: str, *codes: str, use_color: bool = True) -> str:
    if not use_color:
        return text
    return "".join(codes) + text + _RESET


# ── JSON loading ──────────────────────────────────────────────────────────────

_INF_RE = re.compile(r"\bInfinity\b")
_NAN_RE = re.compile(r"\bNaN\b")
_NEG_INF_RE = re.compile(r"-Infinity\b")


def _load_json_lenient(path: Path) -> dict:
    """Load a gate v2 JSON file, replacing bare Infinity/NaN tokens.

    Python's json.dumps(float('inf')) emits 'Infinity' which is valid Python
    but not valid JSON. Six of the 12 existing verdict files contain these
    tokens in oos_pf and gate_v2_metrics.pf_ci_lower. Standard json.load
    crashes on them; this function fixes the raw text before parsing.
    """
    raw = path.read_text(encoding="utf-8")
    raw = _NEG_INF_RE.sub("-1e308", raw)
    raw = _INF_RE.sub("1e308", raw)
    raw = _NAN_RE.sub("null", raw)
    return json.loads(raw)


# ── Metric extraction ─────────────────────────────────────────────────────────

# Gate v2 reasons string patterns for old-format files that don't have a
# structured gate_v2_metrics block.
_REASON_PF_RE = re.compile(r"pf_ci_lower\s*[=:]\s*([\d.eE+\-]+)")
_REASON_P_EDGE_RE = re.compile(r"p_edge\s*[=:]\s*([\d.eE+\-]+)")
_REASON_MC_DD_RE = re.compile(r"mc_95th_dd\s*[=:]\s*([\d.eE+\-]+)")
_REASON_DSR_RE = re.compile(r"dsr\s*[=:]\s*([\d.eE+\-]+)")

_METRIC_THRESHOLDS = {
    "pf_ci_lower": (">=", 1.10),
    "p_edge": (">=", 0.95),
    "mc_95th_dd": ("<=", 0.07),
    "dsr": (">=", 0.10),
    "fixed_params_min_pf": (">=", 1.20),
}


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if (f != f) else f  # NaN check
    except (TypeError, ValueError):
        return None


def extract_metrics(doc: dict) -> dict:
    """Normalise both old-format and new-format verdict docs to a flat dict."""
    m: dict = {}

    # New format: structured gate_v2_metrics block
    gm = doc.get("gate_v2_metrics", {})
    if gm:
        for key in ("pf_ci_lower", "p_edge", "mc_95th_dd", "dsr",
                    "wfo_consistency", "fixed_params_min_pf",
                    "fixed_params_mean_pf", "fixed_params_max_pf"):
            v = gm.get(key)
            m[key] = _safe_float(v) if key not in ("wfo_consistency",) else v

    # Old format: fall back to extracting from reasons strings
    if "pf_ci_lower" not in m or m["pf_ci_lower"] is None:
        reasons = doc.get("gate_v2", {}).get("reasons", "")
        if isinstance(reasons, list):
            reasons = " ".join(reasons)
        for key, pattern in (
            ("pf_ci_lower", _REASON_PF_RE),
            ("p_edge", _REASON_P_EDGE_RE),
            ("mc_95th_dd", _REASON_MC_DD_RE),
            ("dsr", _REASON_DSR_RE),
        ):
            match = pattern.search(str(reasons))
            if match:
                m[key] = _safe_float(match.group(1))

    # Top-level fields
    m["verdict"] = doc.get("verdict") or doc.get("gate_v2", {}).get("verdict", "UNKNOWN")
    m["rank"] = doc.get("rank", 0)
    m["symbol"] = doc.get("symbol", "UNKNOWN")
    m["family"] = doc.get("family", "unknown")
    m["created_at"] = doc.get("created_at", "")
    m["n_oos_trades"] = (
        gm.get("total_oos_trades")
        or doc.get("aux_freshness", {}).get("n_total_oos_trades")
        or doc.get("wfo_config", {}).get("total_oos_trades")
        or 0
    )
    m["wfo_consistency"] = gm.get("wfo_consistency") or doc.get("wfo_consistency", "N/A")

    return m


# ── Trend analysis ────────────────────────────────────────────────────────────

def classify_trend(values: list[float | None]) -> str:
    """Classify metric trend across ranks as RISING / DECLINING / FLAT / N/A."""
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return "N/A"
    deltas = [clean[i + 1] - clean[i] for i in range(len(clean) - 1)]
    pos = sum(1 for d in deltas if d > 0.001)
    neg = sum(1 for d in deltas if d < -0.001)
    n = len(deltas)
    if pos >= n * 0.6:
        return "RISING"
    if neg >= n * 0.6:
        return "DECLINING"
    if pos > neg:
        return "IMPROVING"
    if neg > pos:
        return "WORSENING"
    return "FLAT"


def _trend_diagnosis(metrics_by_rank: list[dict]) -> str | None:
    """Return 'SIGNAL EXHAUSTED' diagnosis string when all ranks FAIL and pf_ci_lower declining."""
    if len(metrics_by_rank) < 3:
        return None
    all_fail = all(m.get("verdict", "FAIL") == "FAIL" for m in metrics_by_rank)
    if not all_fail:
        return None
    pf_values = [m.get("pf_ci_lower") for m in metrics_by_rank]
    trend = classify_trend(pf_values)
    if trend in ("DECLINING", "WORSENING"):
        return (
            f"SIGNAL EXHAUSTED — {len(metrics_by_rank)} consecutive FAILs, "
            f"pf_ci_lower {trend}. "
            "Regime filter or new strategy family recommended."
        )
    return None


# ── Rendering ─────────────────────────────────────────────────────────────────

def _metric_cell(name: str, value: float | None, use_color: bool) -> str:
    if value is None:
        return _c("  N/A  ", _DIM, use_color=use_color)
    op, threshold = _METRIC_THRESHOLDS.get(name, (">=", 0.0))
    passes = (value >= threshold) if op == ">=" else (value <= threshold)
    formatted = f"{value:.4f}"
    if passes:
        return _c(formatted, _GREEN, use_color=use_color)
    else:
        return _c(formatted, _RED, use_color=use_color)


def _verdict_cell(verdict: str, use_color: bool) -> str:
    if verdict == "PASS":
        return _c("  PASS  ", _GREEN, _BOLD, use_color=use_color)
    if verdict == "PASS_ALT":
        return _c("PASS_ALT", _YELLOW, _BOLD, use_color=use_color)
    return _c("  FAIL  ", _RED, _BOLD, use_color=use_color)


def render_symbol_block(
    symbol: str,
    family: str,
    ranks: list[dict],
    use_color: bool,
) -> list[str]:
    lines: list[str] = []
    header = f"{symbol} / {family}  ({len(ranks)} rank{'s' if len(ranks) != 1 else ''})"
    lines.append(_c(f"\n{'─' * 72}", _CYAN, use_color=use_color))
    lines.append(_c(f"  {header}", _BOLD, use_color=use_color))
    lines.append(_c(f"{'─' * 72}", _CYAN, use_color=use_color))

    col_w = 10
    headers = ["Rank", "Verdict", "pf_ci_lo", "p_edge", "mc_dd", "dsr", "fp_min_pf", "wfo", "trades"]
    lines.append("  " + "  ".join(h.ljust(col_w) for h in headers))
    lines.append("  " + "─" * (col_w * len(headers) + 2 * len(headers)))

    for m in ranks:
        rank = str(m.get("rank", "?"))
        verdict = m.get("verdict", "UNKNOWN")
        pf = m.get("pf_ci_lower")
        p_edge = m.get("p_edge")
        mc_dd = m.get("mc_95th_dd")
        dsr = m.get("dsr")
        fp_min = m.get("fixed_params_min_pf")
        wfo = str(m.get("wfo_consistency", "N/A"))
        trades = str(m.get("n_oos_trades", 0))

        row = [
            rank.ljust(col_w),
            _verdict_cell(verdict, use_color).ljust(col_w),
            _metric_cell("pf_ci_lower", pf, use_color).ljust(col_w),
            _metric_cell("p_edge", p_edge, use_color).ljust(col_w),
            _metric_cell("mc_95th_dd", mc_dd, use_color).ljust(col_w),
            _metric_cell("dsr", dsr, use_color).ljust(col_w),
            _metric_cell("fixed_params_min_pf", fp_min, use_color).ljust(col_w),
            wfo[:col_w].ljust(col_w),
            trades.ljust(col_w),
        ]
        lines.append("  " + "  ".join(row))

    # Trend row
    if len(ranks) >= 2:
        def trend_for(key: str) -> str:
            return classify_trend([m.get(key) for m in ranks])

        trend_row = [
            "trend".ljust(col_w),
            "".ljust(col_w),
            trend_for("pf_ci_lower").ljust(col_w),
            trend_for("p_edge").ljust(col_w),
            trend_for("mc_95th_dd").ljust(col_w),
            trend_for("dsr").ljust(col_w),
            trend_for("fixed_params_min_pf").ljust(col_w),
            "".ljust(col_w),
            "".ljust(col_w),
        ]
        lines.append("  " + _c("─" * (col_w * len(headers) + 2 * len(headers)), _DIM, use_color=use_color))
        lines.append("  " + _c("  ".join(trend_row), _DIM, use_color=use_color))

    # Diagnosis
    diagnosis = _trend_diagnosis(ranks)
    if diagnosis:
        lines.append("")
        lines.append("  " + _c(f"!! {diagnosis}", _YELLOW, _BOLD, use_color=use_color))

    return lines


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show gate v2 verdict history for all JARVIS TRADER strategies.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--symbol", help="Filter by symbol (e.g. MNQ, MCL)")
    parser.add_argument("--family", help="Filter by strategy family (e.g. breakout)")
    parser.add_argument("--status", help="Filter by verdict (PASS, PASS_ALT, FAIL)")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colour output")
    parser.add_argument(
        "--verdicts-dir",
        default=None,
        help="Path to gate_v2_verdicts directory (default: auto-detect from script location)",
    )
    args = parser.parse_args()

    use_color = not args.no_color and sys.stdout.isatty()

    # Auto-detect verdicts directory
    if args.verdicts_dir:
        verdicts_dir = Path(args.verdicts_dir)
    else:
        script_dir = Path(__file__).resolve().parent
        # scripts/ is under project root; engine/data/gate_v2_verdicts is sibling of scripts/
        candidates = [
            script_dir.parent / "engine" / "data" / "gate_v2_verdicts",
            script_dir / ".." / "engine" / "data" / "gate_v2_verdicts",
        ]
        verdicts_dir = next((c for c in candidates if c.exists()), candidates[0])

    if not verdicts_dir.exists():
        print(f"Verdicts directory not found: {verdicts_dir}", file=sys.stderr)
        print("Run a backtest first to generate verdict JSON files.", file=sys.stderr)
        sys.exit(1)

    verdict_files = sorted(verdicts_dir.glob("*.json"))
    if not verdict_files:
        print(f"No verdict files found in {verdicts_dir}", file=sys.stderr)
        sys.exit(1)

    # Load and parse all verdict files
    all_metrics: list[dict] = []
    errors: list[str] = []

    for path in verdict_files:
        try:
            doc = _load_json_lenient(path)
            m = extract_metrics(doc)
            m["_path"] = str(path)
            all_metrics.append(m)
        except Exception as exc:
            errors.append(f"  {path.name}: {exc}")

    if errors:
        print(_c("Errors loading files:", _YELLOW, use_color=use_color))
        for e in errors:
            print(e)
        print()

    # Apply filters
    filtered = all_metrics
    if args.symbol:
        filtered = [m for m in filtered if m["symbol"].upper() == args.symbol.upper()]
    if args.family:
        filtered = [m for m in filtered if m["family"].lower() == args.family.lower()]
    if args.status:
        filtered = [m for m in filtered if m["verdict"].upper() == args.status.upper()]

    if not filtered:
        print("No verdicts match the specified filters.")
        sys.exit(0)

    # Group by (symbol, family) and sort by rank within each group
    groups: dict[tuple, list[dict]] = {}
    for m in filtered:
        key = (m["symbol"], m["family"])
        groups.setdefault(key, []).append(m)

    for key in groups:
        groups[key].sort(key=lambda m: m.get("rank", 0))

    # Render
    output_lines: list[str] = []
    total_pass = sum(1 for m in filtered if m["verdict"] in ("PASS", "PASS_ALT"))
    total_fail = sum(1 for m in filtered if m["verdict"] == "FAIL")

    output_lines.append(_c(
        f"\nJARVIS TRADER — Gate v2 Verdict History  "
        f"({len(filtered)} verdicts: {total_pass} pass, {total_fail} fail)",
        _BOLD, use_color=use_color,
    ))

    for (symbol, family), ranks in sorted(groups.items()):
        output_lines.extend(render_symbol_block(symbol, family, ranks, use_color))

    output_lines.append(_c(f"\n{'─' * 72}", _CYAN, use_color=use_color))
    output_lines.append(
        f"  Verdicts dir : {verdicts_dir}\n"
        f"  Total files  : {len(verdict_files)}\n"
        f"  Loaded       : {len(all_metrics)}\n"
        f"  Matching     : {len(filtered)}"
    )

    for line in output_lines:
        print(line)


if __name__ == "__main__":
    main()
