"""Generate a markdown strategy-portfolio scoreboard from gate v2 verdict files.

Usage:
    python engine/scripts/generate_scoreboard.py
    python engine/scripts/generate_scoreboard.py --out engine/data/SCOREBOARD.md

Reads all *.json in engine/data/gate_v2_verdicts/ (not archive/).
Handles the Infinity literal that json.loads rejects.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_VERDICTS_DIR = Path(__file__).parent.parent / "data" / "gate_v2_verdicts"


def _load_json(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    # json.loads rejects bare Infinity; replace with null before parsing
    text = re.sub(r":\s*Infinity\b", ": null", text)
    return json.loads(text)


def _parse_float(reasons: list[str], pattern: str) -> float | None:
    for r in reasons:
        m = re.search(pattern, r)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def _parse_str(reasons: list[str], pattern: str) -> str | None:
    for r in reasons:
        m = re.search(pattern, r)
        if m:
            return m.group(1)
    return None


def _extract_metrics(doc: dict) -> dict:
    """Extract key metrics, preferring gate_v2_metrics over reason-string parsing."""
    m = doc.get("gate_v2_metrics") or {}
    gv2 = doc.get("gate_v2") or {}
    core_reasons = gv2.get("core_reasons") or []
    alt_reasons = gv2.get("alt_reasons") or []
    all_reasons = core_reasons + alt_reasons

    pf_ci_lower = m.get("pf_ci_lower") or _parse_float(core_reasons, r"mbb_pf_ci_lower=([\d.]+)")
    p_edge = m.get("p_edge") or _parse_float(core_reasons, r"p_positive_edge=([\d.]+)")
    mc_dd_pct = m.get("mc_95th_dd_pct") or _parse_float(core_reasons, r"mc_95th_dd_pct=([\d.]+)")
    dsr = m.get("dsr") or _parse_float(core_reasons, r"dsr=([\d.]+)")
    wfo = m.get("wfo_consistency") or _parse_str(alt_reasons, r"rolling_wfo=(\w+)")
    cost = m.get("cost_survives_through") or _parse_str(all_reasons, r"cost_survives_through=(\w+)")

    return {
        "pf_ci_lower": pf_ci_lower,
        "p_edge": p_edge,
        "mc_dd_pct": mc_dd_pct,
        "dsr": dsr,
        "wfo": wfo,
        "cost": cost,
    }


def _fmt(val: float | None, decimals: int = 2, suffix: str = "") -> str:
    if val is None:
        return "-"
    return f"{val:.{decimals}f}{suffix}"


def _sort_key(row: dict) -> tuple:
    verdict_order = {"PASS": 0, "FAIL": 1}
    path_order = {"core": 0, "alt": 1, None: 2}
    return (
        verdict_order.get(row["verdict"], 9),
        path_order.get(row["passed_via"], 2),
        row["symbol"],
        row["family"],
        row["rank"],
    )


def build_scoreboard(verdicts_dir: Path) -> str:
    json_files = sorted(verdicts_dir.glob("*.json"))
    if not json_files:
        return "_No verdict files found._\n"

    rows = []
    for path in json_files:
        try:
            doc = _load_json(path)
        except Exception as exc:
            print(f"WARN: failed to parse {path.name}: {exc}", file=sys.stderr)
            continue

        metrics = _extract_metrics(doc)
        created = doc.get("created_at", "")
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                created = dt.strftime("%Y-%m-%d")
            except ValueError:
                created = created[:10]

        rows.append(
            {
                "symbol": doc.get("symbol", "?"),
                "family": doc.get("family", "?"),
                "rank": doc.get("rank", 0),
                "verdict": doc.get("verdict", "?"),
                "passed_via": doc.get("passed_via"),
                "created": created,
                **metrics,
            }
        )

    rows.sort(key=_sort_key)

    now_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Strategy Scoreboard",
        "",
        f"_Generated {now_utc} from {len(rows)} active verdict(s). Archive: {len(list((verdicts_dir / 'archive').glob('*.json') if (verdicts_dir / 'archive').exists() else []))} files._",
        "",
        "| Strategy | Verdict | Path | pf_ci_lower | p_edge | mc_dd% | DSR | WFO | Cost survives | Updated |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for r in rows:
        strategy = f"{r['symbol']}_{r['family']}_r{r['rank']}"
        verdict = r["verdict"]
        path = r["passed_via"] or "-"
        pf = _fmt(r["pf_ci_lower"])
        pe = _fmt(r["p_edge"], decimals=3)
        dd = _fmt(r["mc_dd_pct"], decimals=2, suffix="%")
        dsr = _fmt(r["dsr"], decimals=3)
        wfo = r["wfo"] or "-"
        cost = r["cost"] or "-"
        created = r["created"] or "-"

        lines.append(
            f"| {strategy} | {verdict} | {path} | {pf} | {pe} | {dd} | {dsr} | {wfo} | {cost} | {created} |"
        )

    lines += [
        "",
        "## Thresholds",
        "",
        "| Criterion | Core | ALT |",
        "|---|---|---|",
        "| pf_ci_lower | >= 1.10 | - |",
        "| p_edge | >= 0.95 | relaxed |",
        "| mc_95th_dd% | <= 5.0% | <= 4.0% |",
        "| DSR | >= 0.10 | >= 0.30 |",
        "| WFO consistency | - | MODERATE/STRONG |",
        "| Fixed params min PF | - | >= 1.20 |",
        "| Cost survives | - | >= realistic |",
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate gate v2 strategy scoreboard")
    parser.add_argument("--out", type=Path, help="Write markdown output to this file")
    parser.add_argument(
        "--dir",
        type=Path,
        default=_VERDICTS_DIR,
        help="Directory containing verdict JSON files",
    )
    args = parser.parse_args()

    scoreboard = build_scoreboard(args.dir)
    print(scoreboard)

    if args.out:
        args.out.write_text(scoreboard, encoding="utf-8")
        print(f"\nWrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
