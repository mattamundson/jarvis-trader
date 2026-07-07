"""Diversification audit — MES rank11 vs MGC rank4 OOS window correlation.

Reads the two active PASS verdicts and computes:
1. Window-level OOS PF values aligned by start month
2. Pearson correlation of OOS PFs across aligned windows
3. Proportion of windows where both strategies were profitable
4. Proportion where they moved in opposite directions (true diversification signal)

Usage (from engine/ directory):
    .venv/Scripts/python backtest/diversification_audit.py
    .venv/Scripts/python backtest/diversification_audit.py --write  # save report

Interpretation:
    Correlation < 0.3 → low correlation, genuine diversification
    Correlation 0.3–0.6 → moderate; portfolio still benefits from both
    Correlation > 0.6 → high; strategies may be co-moving (macro regime co-dependence)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VERDICTS_DIR = engine_root / "data" / "gate_v2_verdicts"
REPORT_PATH = engine_root / "data" / "DIVERSIFICATION_AUDIT.md"

MES_VERDICT = VERDICTS_DIR / "MES_trend_rank11.json"
MGC_VERDICT = VERDICTS_DIR / "MGC_trend_rank4.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_period_start(period_str: str) -> str:
    """Extract start YYYY-MM from 'YYYY-MM -> YYYY-MM'."""
    return period_str.split("->")[0].strip()


def _load_windows(path: Path) -> dict[str, dict]:
    """Return dict keyed by OOS start month ('YYYY-MM') → window record."""
    d = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict] = {}
    for w in d.get("windows", []):
        period = w.get("oos_period", "")
        if not period:
            continue
        start = _parse_period_start(period)
        result[start] = w
    return result


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Compute Pearson r. Returns None if n < 3 or zero variance."""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    denom_x = sum((x - mx) ** 2 for x in xs) ** 0.5
    denom_y = sum((y - my) ** 2 for y in ys) ** 0.5
    if denom_x == 0 or denom_y == 0:
        return None
    return num / (denom_x * denom_y)


# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------


def run_audit() -> str:
    mes_windows = _load_windows(MES_VERDICT)
    mgc_windows = _load_windows(MGC_VERDICT)

    # Align by start month — inner join on months present in both
    common_months = sorted(set(mes_windows) & set(mgc_windows))

    lines: list[str] = []
    lines.append("# Diversification Audit — MES Rank11 vs MGC Rank4")
    lines.append("")
    now_utc = datetime.now(tz=timezone.utc)
    lines.append(f"*Generated {now_utc.strftime('%Y-%m-%d %H:%M')} UTC*")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "Window-level OOS PF values are aligned by OOS start month and compared. "
        "MES rank11 uses 1-month OOS windows; MGC rank4 uses 2-month OOS windows. "
        "Months where only one strategy has a window are excluded from the correlation "
        "calculation (inner join on start month)."
    )
    lines.append("")
    lines.append(
        "**Limitation:** This proxy uses per-window aggregate PF, not daily equity curves. "
        "True daily PnL correlation would require re-running backtests with a "
        "`--export-daily-pnl` flag (not yet implemented). This audit is a conservative "
        "first-pass — aggregate PF correlation tends to *overstate* true correlation "
        "vs daily PnL correlation."
    )
    lines.append("")

    # Build aligned table
    mes_pfs: list[float] = []
    mgc_pfs: list[float] = []

    table_rows: list[tuple] = []
    for month in common_months:
        mw = mes_windows[month]
        gw = mgc_windows[month]
        mes_pf = mw.get("oos_pf")
        mgc_pf = gw.get("oos_pf")
        mes_trades = mw.get("oos_trades", 0)
        mgc_trades = gw.get("oos_trades", 0)

        if mes_pf is None or mgc_pf is None:
            continue

        # Cap inf (no losers) at 5.0 for correlation math
        mes_pf_capped = min(float(mes_pf), 5.0) if mes_pf != float("inf") else 5.0
        mgc_pf_capped = min(float(mgc_pf), 5.0) if mgc_pf != float("inf") else 5.0

        mes_pfs.append(mes_pf_capped)
        mgc_pfs.append(mgc_pf_capped)

        mes_disp = "inf" if mes_pf == float("inf") else f"{mes_pf:.3f}"
        mgc_disp = "inf" if mgc_pf == float("inf") else f"{mgc_pf:.3f}"
        mes_win = "PASS" if mes_pf > 1.0 or mes_pf == float("inf") else "FAIL"
        mgc_win = "PASS" if mgc_pf > 1.0 or mgc_pf == float("inf") else "FAIL"
        both_win = "both" if mes_pf > 1.0 and mgc_pf > 1.0 else ""
        opposite = "opp" if (mes_pf > 1.0) != (mgc_pf > 1.0) else ""

        table_rows.append(
            (
                month,
                mes_disp,
                mes_trades,
                mes_win,
                mgc_disp,
                mgc_trades,
                mgc_win,
                (both_win or opposite) or "-",
            )
        )

    lines.append("## Window-Level OOS PF Comparison")
    lines.append("")
    lines.append("| Month | MES PF | MES trades | MES | MGC PF | MGC trades | MGC | Both |")
    lines.append("|-------|--------|------------|-----|--------|------------|-----|------|")
    for row in table_rows:
        month, mf, mt, mw, gf, gt, gw, both = row
        lines.append(f"| {month} | {mf} | {mt} | {mw} | {gf} | {gt} | {gw} | {both} |")

    lines.append("")

    # Statistics
    n = len(mes_pfs)
    both_profitable = sum(1 for m, g in zip(mes_pfs, mgc_pfs, strict=False) if m > 1.0 and g > 1.0)
    mes_only = sum(1 for m, g in zip(mes_pfs, mgc_pfs, strict=False) if m > 1.0 and g <= 1.0)
    mgc_only = sum(1 for m, g in zip(mes_pfs, mgc_pfs, strict=False) if m <= 1.0 and g > 1.0)
    neither = sum(1 for m, g in zip(mes_pfs, mgc_pfs, strict=False) if m <= 1.0 and g <= 1.0)
    opposite_count = mes_only + mgc_only

    r = _pearson(mes_pfs, mgc_pfs)

    lines.append("## Statistics")
    lines.append("")
    lines.append(f"- **Aligned windows:** {n}")
    lines.append(f"- **Both profitable:** {both_profitable}/{n} ({100*both_profitable/n:.0f}%)")
    lines.append(f"- **MES only profitable:** {mes_only}/{n} ({100*mes_only/n:.0f}%)")
    lines.append(f"- **MGC only profitable:** {mgc_only}/{n} ({100*mgc_only/n:.0f}%)")
    lines.append(f"- **Neither profitable:** {neither}/{n} ({100*neither/n:.0f}%)")
    lines.append(
        f"- **Opposite direction (one PASS, one FAIL):** {opposite_count}/{n} ({100*opposite_count/n:.0f}%)"
    )
    lines.append("")

    if r is not None:
        if r < 0.3:
            corr_label = "LOW — genuine diversification"
        elif r < 0.6:
            corr_label = (
                "MODERATE — portfolio benefit present but strategies co-move in risk-off periods"
            )
        else:
            corr_label = "HIGH — strategies likely co-depend on the same macro regime"

        lines.append(f"**OOS PF Pearson correlation:** r = {r:.3f} → {corr_label}")
    else:
        lines.append("**OOS PF Pearson correlation:** insufficient aligned windows for calculation")

    lines.append("")
    lines.append("## Verdict")
    lines.append("")

    if r is not None:
        if r < 0.3:
            lines.append(
                "MES trend (equity-index) and MGC trend (gold) are **lowly correlated** at the "
                "OOS window level. Running both simultaneously provides genuine portfolio "
                "diversification — each strategy covers months the other cannot."
            )
        elif r < 0.6:
            lines.append(
                "MES and MGC show **moderate OOS PF correlation**. The portfolio benefits from "
                "running both, but they likely share a macro-regime dependency (both struggle "
                "in low-volatility chop or risk-off spikes). "
                "Acceptable diversification for a 2-strategy portfolio."
            )
        else:
            lines.append(
                "MES and MGC show **high OOS PF correlation**. Investigate whether a shared "
                "regime condition (e.g. high-VIX risk-off episodes) is driving both to fail "
                "simultaneously. Consider adding a third uncorrelated asset class."
            )

    lines.append("")
    lines.append("## Next Step for Deeper Audit")
    lines.append("")
    lines.append(
        "For a daily equity-curve correlation: add `--export-daily-pnl <path>` to each "
        "WFO runner and rerun. Compute Pearson r on the overlapping daily PnL series. "
        "Window-level aggregate PF tends to overstate correlation vs daily PnL, so the "
        "true daily r is likely at or below the r computed here."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true", help="Write DIVERSIFICATION_AUDIT.md")
    args = parser.parse_args()

    if not MES_VERDICT.exists():
        print(f"ERROR: {MES_VERDICT} not found", file=sys.stderr)
        return 1
    if not MGC_VERDICT.exists():
        print(f"ERROR: {MGC_VERDICT} not found", file=sys.stderr)
        return 1

    report = run_audit()
    sys.stdout.buffer.write(report.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")

    if args.write:
        REPORT_PATH.write_text(report, encoding="utf-8")
        sys.stderr.write(f"\n[audit] Written to {REPORT_PATH}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
