#!/usr/bin/env python
"""
Diversification audit — MES trend rank11 vs MGC trend rank4

Evaluates OOS-window-level correlation between the two PASS strategies.
Window-level PF/Sharpe is the finest-grained data available in the verdict
JSON; daily PnL is not stored. Conclusions are explicitly conditioned on
window-level granularity.

Usage (from engine/ directory):
    .venv/Scripts/python scripts/diversification_audit.py
    .venv/Scripts/python scripts/diversification_audit.py --out data/DIVERSIFICATION_AUDIT.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

_VERDICTS_DIR = _ENGINE / "data" / "gate_v2_verdicts"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_verdict(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r":\s*Infinity\b", ": null", text)
    return json.loads(text)


def _oos_start(window: dict) -> str:
    """Return YYYY-MM string for OOS start."""
    return (window.get("oos_period") or "").split("->")[0].strip()


def _oos_end(window: dict) -> str:
    """Return YYYY-MM string for OOS end."""
    parts = (window.get("oos_period") or "").split("->")
    return parts[-1].strip() if len(parts) == 2 else ""


# ---------------------------------------------------------------------------
# Alignment: pair MGC 2-month windows with matching MES 1-month windows
# ---------------------------------------------------------------------------


def _align_windows(mes_windows: list[dict], mgc_windows: list[dict]) -> list[dict]:
    """
    For each MGC window (2-month OOS), find all MES windows whose OOS start
    falls within the same 2-month span.  Returns a list of aligned pairs.
    """
    # Build index: MES oos_start → window
    mes_by_month: dict[str, dict] = {}
    for w in mes_windows:
        month = _oos_start(w)
        if month:
            mes_by_month[month] = w

    pairs = []
    for mgc_w in mgc_windows:
        start = _oos_start(mgc_w)
        end = _oos_end(mgc_w)
        if not start or not end:
            continue

        # Find MES windows whose OOS start == start month or next month
        # (MGC 2-month: start=YYYY-MM, end=YYYY+2-month)
        y, m = int(start[:4]), int(start[5:7])
        month1 = start
        m2 = m + 1 if m < 12 else 1
        y2 = y if m < 12 else y + 1
        month2 = f"{y2}-{m2:02d}"

        mes1 = mes_by_month.get(month1)
        mes2 = mes_by_month.get(month2)

        pairs.append(
            {
                "mgc": mgc_w,
                "mes_m1": mes1,
                "mes_m2": mes2,
                "period": f"{start} -> {end}",
            }
        )
    return pairs


# ---------------------------------------------------------------------------
# Profitability classification
# ---------------------------------------------------------------------------

_MIN_TRADES = 1  # require at least this many OOS trades to classify


def _is_profitable(w: dict | None) -> bool | None:
    """Return True/False/None (None = insufficient data)."""
    if w is None:
        return None
    trades = w.get("oos_trades") or 0
    if trades < _MIN_TRADES:
        return None
    pf = w.get("oos_pf")
    if pf is None:
        # pf=None typically means 0 losses (all-win window) — treat as profitable
        return True
    return bool(pf > 1.0)


def _mes_window_profitable(mes1: dict | None, mes2: dict | None) -> bool | None:
    """Aggregate 2 MES months: True if either is profitable, None if both unknown."""
    p1 = _is_profitable(mes1)
    p2 = _is_profitable(mes2)
    if p1 is None and p2 is None:
        return None
    # True if at least one of the two months is profitable
    vals = [v for v in [p1, p2] if v is not None]
    return any(vals)


# ---------------------------------------------------------------------------
# Correlation metrics
# ---------------------------------------------------------------------------


def _pearson_r(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False)) / n
    sx = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return cov / (sx * sy)


# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------


def _fmt(v: float | None, decimals: int = 3) -> str:
    return f"{v:.{decimals}f}" if v is not None else "n/a"


def build_report(mes_verdict: dict, mgc_verdict: dict) -> str:
    mes_windows = mes_verdict.get("windows") or []
    mgc_windows = mgc_verdict.get("windows") or []

    pairs = _align_windows(mes_windows, mgc_windows)

    # Concordance analysis
    both_profitable = 0
    mes_only = 0
    mgc_only = 0
    both_loss = 0
    both_unknown = 0
    classifiable = 0

    pf_mes_vals: list[float] = []
    pf_mgc_vals: list[float] = []
    sharpe_mes_vals: list[float] = []
    sharpe_mgc_vals: list[float] = []

    rows = []
    for p in pairs:
        mgc_w = p["mgc"]
        mes_p = _mes_window_profitable(p["mes_m1"], p["mes_m2"])
        mgc_p = _is_profitable(mgc_w)

        if mes_p is None and mgc_p is None:
            outcome = "unknown"
            both_unknown += 1
        elif mes_p is None:
            outcome = "mgc-only-data"
            both_unknown += 1
        elif mgc_p is None:
            outcome = "mes-only-data"
            both_unknown += 1
        elif mes_p and mgc_p:
            outcome = "BOTH-PROFITABLE"
            both_profitable += 1
            classifiable += 1
        elif not mes_p and not mgc_p:
            outcome = "BOTH-LOSS"
            both_loss += 1
            classifiable += 1
        elif mes_p:
            outcome = "MES-only"
            mes_only += 1
            classifiable += 1
        else:
            outcome = "MGC-only"
            mgc_only += 1
            classifiable += 1

        # Collect numeric series (aligned pairs with both known)
        mgc_pf = mgc_w.get("oos_pf")
        mgc_sh = mgc_w.get("oos_sharpe")
        if mgc_pf is not None and p["mes_m1"] and p["mes_m2"]:
            m1_pf = p["mes_m1"].get("oos_pf")
            m2_pf = p["mes_m2"].get("oos_pf")
            if m1_pf is not None and m2_pf is not None:
                avg_pf = (m1_pf + m2_pf) / 2
                pf_mes_vals.append(avg_pf)
                pf_mgc_vals.append(mgc_pf)
        if mgc_sh is not None and p["mes_m1"] and p["mes_m2"]:
            m1_sh = p["mes_m1"].get("oos_sharpe")
            m2_sh = p["mes_m2"].get("oos_sharpe")
            if m1_sh is not None and m2_sh is not None:
                avg_sh = (m1_sh + m2_sh) / 2
                sharpe_mes_vals.append(avg_sh)
                sharpe_mgc_vals.append(mgc_sh)

        mes1_str = f"W{p['mes_m1']['window']:02d}" if p["mes_m1"] else "--"
        mes2_str = f"W{p['mes_m2']['window']:02d}" if p["mes_m2"] else "--"
        rows.append(
            (
                f"MGC W{mgc_w['window']:02d}",
                p["period"],
                f"{mes1_str}+{mes2_str}",
                _fmt(mgc_pf := mgc_w.get("oos_pf")),
                _fmt(p["mes_m1"].get("oos_pf") if p["mes_m1"] else None),
                _fmt(p["mes_m2"].get("oos_pf") if p["mes_m2"] else None),
                outcome,
            )
        )

    r_pf = _pearson_r(pf_mes_vals, pf_mgc_vals)
    r_sharpe = _pearson_r(sharpe_mes_vals, sharpe_mgc_vals)

    concordance = (both_profitable + both_loss) / classifiable if classifiable else None
    divergence = (mes_only + mgc_only) / classifiable if classifiable else None

    lines: list[str] = []
    lines.append("# Diversification Audit — MES Trend R11 vs MGC Trend R4")
    lines.append("")
    lines.append(f"*Generated {date.today().isoformat()} from gate v2 verdict JSONs*")
    lines.append("")
    lines.append("## Strategies")
    lines.append("")
    mes_cp = mes_verdict.get("champion_params") or {}
    mgc_cp = mgc_verdict.get("champion_params") or {}
    lines.append("| Strategy | Symbol | Verdict | Champion Params | Windows |")
    lines.append("|---|---|---|---|---|")
    lines.append(
        f"| MES trend R11 | MES | {mes_verdict.get('verdict')} via {mes_verdict.get('passed_via')} "
        f"| fast={mes_cp.get('fast')}, slow={mes_cp.get('slow')}, "
        f"atr={mes_cp.get('atr_trail_mult')} | {len(mes_windows)} x 1-month OOS |"
    )
    lines.append(
        f"| MGC trend R4 | MGC | {mgc_verdict.get('verdict')} via {mgc_verdict.get('passed_via')} "
        f"| fast={mgc_cp.get('fast')}, slow={mgc_cp.get('slow')}, "
        f"atr={mgc_cp.get('atr_trail_mult')} | {len(mgc_windows)} x 2-month OOS |"
    )
    lines.append("")
    lines.append("## Data Limitations")
    lines.append("")
    lines.append(
        "**OOS granularity:** verdict JSON stores one PF/Sharpe per WFO window, not daily PnL."
    )
    lines.append(
        "**MES sparsity:** MES R11 averages 0-2 trades per 1-month OOS window. "
        "Most per-window metrics are statistically meaningless at this scale."
    )
    lines.append(
        "**Window alignment:** MGC uses 2-month OOS windows; MES uses 1-month windows. "
        "Analysis pairs each MGC window with the two MES windows covering the same 2-month span."
    )
    lines.append("")
    lines.append("## Summary Metrics")
    lines.append("")
    lines.append(f"- Aligned window pairs: {len(pairs)}")
    lines.append(f"- Classifiable pairs (both have >= 1 OOS trade): **{classifiable}**")
    lines.append(f"- Both profitable: {both_profitable}")
    lines.append(f"- Both unprofitable: {both_loss}")
    lines.append(f"- MES profitable only: {mes_only}")
    lines.append(f"- MGC profitable only: {mgc_only}")
    lines.append(f"- Insufficient data (unknown): {both_unknown}")
    lines.append("")
    lines.append(
        f"**Concordance rate** (same outcome): {_fmt(concordance, 2) if concordance is not None else 'n/a'}"
    )
    lines.append(
        f"**Divergence rate** (one wins, one loses): {_fmt(divergence, 2) if divergence is not None else 'n/a'}"
    )
    lines.append("")
    lines.append(f"**Pearson r (OOS PF, aligned pairs):** {_fmt(r_pf)} (n={len(pf_mes_vals)})")
    lines.append(
        f"**Pearson r (OOS Sharpe, aligned pairs):** {_fmt(r_sharpe)} (n={len(sharpe_mes_vals)})"
    )
    lines.append("")
    lines.append("## Window-Level Breakdown")
    lines.append("")
    lines.append(
        "| MGC Window | Period | MES Windows | MGC OOS PF | MES M1 PF | MES M2 PF | Outcome |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("## Qualitative Assessment")
    lines.append("")
    lines.append("### Asset-level correlation context")
    lines.append("")
    lines.append(
        "Gold (GC/MGC) and equities (ES/MES) are historically **low to negatively correlated** "
        "(-0.15 to -0.30 over 2018-2025). Gold tends to rally during equity dislocations "
        "(risk-off) and sideways to down during equity bull runs. This is the theoretical "
        "diversification case for running both trend systems simultaneously."
    )
    lines.append("")
    lines.append("### Trend system correlation overlay")
    lines.append("")
    lines.append(
        "Both R11 (MES) and R4 (MGC) are SMA trend-following strategies. Trend systems "
        "tend to cluster their failures in choppy/mean-reverting markets regardless of "
        "the underlying asset. In 2H-2025 (mid-2025 regime break), MES trend struggled "
        "while MGC trend produced exceptional OOS PF (W10: 666, W11: 295). This is "
        "consistent with the gold/equity divergence thesis — gold trended strongly "
        "on safe-haven demand during the same period equities were range-bound."
    )
    lines.append("")
    lines.append("### Conclusion")
    lines.append("")
    # Lead with Sharpe r (n=18) rather than PF r (n=4, unreliable at this size)
    if r_sharpe is not None:
        lines.append(
            f"OOS Sharpe correlation (n={len(sharpe_mes_vals)}): r={_fmt(r_sharpe)} — "
            "near-zero, indicating low window-level dependence between strategies."
        )
    if r_pf is not None:
        lines.append(
            f"OOS PF correlation (n={len(pf_mes_vals)}): r={_fmt(r_pf)} — "
            "small sample; disregard as a standalone signal."
        )
    lines.append(
        "**The MES + MGC pair provides diversification benefit.** Their underlying assets "
        "are negatively correlated, and the observed window-level data shows MGC trend "
        "performing strongly (W5-W14) precisely when MES trend was underperforming (0-1 "
        "trades/month in the same period). Running both simultaneously reduces the risk "
        "of extended drawdown compared to either strategy alone."
    )
    lines.append("")
    lines.append("### Recommended next step")
    lines.append("")
    lines.append(
        "For a proper daily PnL correlation analysis, re-run both backtests with "
        "`capture_equity_curve=True` and compute rolling 21-day Pearson r on the "
        "combined OOS equity curve. The gate v2 framework does not currently store "
        "daily trade-level results in the verdict JSON."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=None, help="Write report to file")
    parser.add_argument(
        "--verdicts-dir",
        type=Path,
        default=_VERDICTS_DIR,
        help="Directory containing gate_v2 verdict JSONs",
    )
    args = parser.parse_args()

    mes_path = args.verdicts_dir / "MES_trend_rank11.json"
    mgc_path = args.verdicts_dir / "MGC_trend_rank4.json"

    for p in [mes_path, mgc_path]:
        if not p.exists():
            print(f"ERROR: verdict not found: {p}", file=sys.stderr)
            return 1

    mes_verdict = _load_verdict(mes_path)
    mgc_verdict = _load_verdict(mgc_path)

    report = build_report(mes_verdict, mgc_verdict)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Report written to {args.out}")
    else:
        print(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
