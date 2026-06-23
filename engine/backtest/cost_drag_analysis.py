#!/usr/bin/env python
"""JARVIS TRADER -- cost-drag decomposition for discovery-factory families (Phase 3).

A family can FAIL gate-v2 for two very different reasons, and the remedy differs:

  - NO_EDGE      : the signal has no edge even at ZERO cost -> abandon the family.
  - COST_KILLED  : a real gross edge exists but commission+slippage eats it ->
                   pursue better execution (passive/limit fills, fewer but
                   higher-conviction trades), NOT a new signal.
  - ROBUST       : clears the gate threshold even net (shouldn't appear among
                   FAILs; a guard that the decomposition is wired correctly).

The leaderboard's net `pf_ci_lower` (~0.5-0.7 for the 15m MES families) cannot
distinguish these. `cost_survives_through` is a FULL-DATA champion metric, not an
out-of-sample one. This tool gives an apples-to-apples OOS read: it re-runs a
spec's WFO grid at ZERO cost and at REALISTIC cost (the gate's decision tier) and
compares the aggregate OOS `pf_ci_lower`. The gap is the cost drag; the gross
number says whether any edge is there to rescue.

Safety: research only. Reuses the factory registry + the canonical
`wfo_lifecycle` pipeline (never reimplements gate math); writes a report to
data/cost_drag/ -- deliberately NOT gate_v2_verdicts/ (the store the live engine
reads), so nothing here can authorize trading. Pure offline backtest over cached
bars: no signals.py/config/.env writes, no engine restart, no live endpoint.

Usage (from engine/):
    .venv/Scripts/python -m backtest.cost_drag_analysis                 # all 15m specs
    .venv/Scripts/python -m backtest.cost_drag_analysis --interval 15m  # explicit
    .venv/Scripts/python -m backtest.cost_drag_analysis --symbol MES --family donchian
    .venv/Scripts/python -m backtest.cost_drag_analysis --cache-dir <path>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# Mirror the factory's offline placeholder so standalone/worktree runs don't trip
# config.TradingConfig()'s API_KEY fail-fast. Real .env wins when present.
os.environ.setdefault("API_KEY", "offline-cost-drag")

from backtest._gate_v2_helpers import GATE_PF_CI_LOWER, bootstrap_pf_ci_lower  # noqa: E402
from backtest.discovery_factory import (  # noqa: E402
    _make_run_fn,
    _select,
    _wfo_config,
    default_registry,
    load_interval_bars,
)
from backtest.wfo_lifecycle import run_wfo  # noqa: E402

# The gate's decision tier is "realistic"; zero is the gross-edge reference.
ZERO_COST = {"commission": 0.0, "slippage_ticks": 0.0}
REALISTIC_COST = {"commission": 0.62, "slippage_ticks": 2.0}
REPORT_DIR = engine_root / "data" / "cost_drag"
FACTORY_DIR = engine_root / "data" / "discovery_factory"


def _load_champion(label: str, factory_dir: Path = FACTORY_DIR) -> dict | None:
    """Read a spec's already-selected champion params from its factory verdict.

    Enables a fast 'champion-only' decomposition: rather than re-running the full
    param grid through WFO twice (which is ~n_combos× the work and unnecessary for
    a cost question), we hold the strategy fixed at the champion the factory
    already selected and vary ONLY cost. Returns None if no verdict exists.
    """
    path = factory_dir / f"{label}.json"
    if not path.exists():
        return None
    try:
        champ = json.loads(path.read_text()).get("champion_params")
        return champ or None
    except (json.JSONDecodeError, OSError):
        return None


def classify_cost_drag(
    gross_pf_ci: float, net_pf_ci: float, threshold: float = GATE_PF_CI_LOWER
) -> str:
    """Bucket a family by where its OOS edge lives relative to the gate threshold.

    ROBUST       -> net already clears the floor (not actually cost-limited)
    COST_KILLED  -> gross clears but net does not (a real edge eaten by cost)
    NO_EDGE      -> gross does not clear (no edge even at zero cost)
    """
    if net_pf_ci >= threshold:
        return "ROBUST"
    if gross_pf_ci >= threshold:
        return "COST_KILLED"
    return "NO_EDGE"


def _cost_injecting_run_fn(base_run_fn: Callable, cost: dict) -> Callable:
    """Wrap a factory run_fn so every backtest in a WFO grid uses one cost tier.

    run_wfo searches the param grid (signal kwargs only) and never injects cost,
    so the underlying Backtester would fall back to its defaults. Merging `cost`
    last forces a uniform tier across IS search and OOS evaluation alike.
    """

    def run_fn(df, params):
        return base_run_fn(df, {**params, **cost})

    return run_fn


def _oos_pf_ci(oos_results: list, min_trades: int) -> tuple[float, int]:
    """Aggregate OOS profit-factor CI lower bound + total trades.

    Mirrors compute_gate_v2's aggregation: only windows meeting min_trades feed
    the bootstrap PF CI, but every window's trades count toward the total.
    """
    qualified = [r for r in oos_results if r.total_trades >= min_trades]
    pfs = [r.profit_factor for r in qualified]
    pf_ci = bootstrap_pf_ci_lower(pfs) if pfs else 0.0
    total = sum(r.total_trades for r in oos_results)
    return pf_ci, total


def analyze_spec(spec, cache_dir: Path, champion_only: bool = False) -> dict:
    """Run one spec's WFO at zero and realistic cost; decompose the drag.

    champion_only=True holds the strategy fixed at the factory-selected champion
    (a 1-combo grid), varying only cost -- a faithful and far cheaper way to
    answer "is there gross edge?". Falls back to the full grid if no champion
    verdict is on disk.
    """
    df = load_interval_bars(spec.symbol, spec.interval, cache_dir)
    base = _make_run_fn(spec)
    cfg = _wfo_config(spec)
    mt = spec.min_oos_trades_per_window

    grid = spec.param_grid
    mode = "full_grid"
    if champion_only:
        champ = _load_champion(spec.label)
        if champ is not None:
            grid = [champ]
            mode = "champion_only"

    gross_oos, _ = run_wfo(df, grid, _cost_injecting_run_fn(base, ZERO_COST), cfg, min_trades=mt)
    net_oos, _ = run_wfo(df, grid, _cost_injecting_run_fn(base, REALISTIC_COST), cfg, min_trades=mt)
    gross_pf, gross_tr = _oos_pf_ci(gross_oos, mt)
    net_pf, net_tr = _oos_pf_ci(net_oos, mt)

    return {
        "label": spec.label,
        "symbol": spec.symbol,
        "family": spec.family,
        "interval": spec.interval,
        "mode": mode,
        "champion_params": grid[0] if mode == "champion_only" else None,
        "gross_pf_ci_lower": round(gross_pf, 4),
        "net_pf_ci_lower": round(net_pf, 4),
        "cost_drag_pf": round(gross_pf - net_pf, 4),
        "classification": classify_cost_drag(gross_pf, net_pf),
        "threshold": GATE_PF_CI_LOWER,
        "gross_oos_trades": gross_tr,
        "net_oos_trades": net_tr,
        "n_combos": len(grid),
        "source_file": df.attrs.get("source_file"),
    }


def _format_report(rows: list[dict]) -> str:
    h = (
        f"{'LABEL':<28}{'CLASS':<13}{'grossPFci':>10}{'netPFci':>9}"
        f"{'dragPF':>8}{'grossTr':>8}{'netTr':>7}"
    )
    lines = [h, "-" * len(h)]
    for r in rows:
        lines.append(
            f"{r['label']:<28}{r['classification']:<13}"
            f"{r['gross_pf_ci_lower']:>10}{r['net_pf_ci_lower']:>9}"
            f"{r['cost_drag_pf']:>8}{r['gross_oos_trades']:>8}{r['net_oos_trades']:>7}"
        )
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    lines.append("")
    lines.append("  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JARVIS cost-drag decomposition (Phase 3)")
    parser.add_argument("--symbol", help="filter to one symbol")
    parser.add_argument("--family", help="filter to one family")
    parser.add_argument(
        "--interval", default="15m", help="interval to analyze (default 15m -- the pivot TF)"
    )
    parser.add_argument(
        "--cache-dir", default=str(engine_root / "backtest" / "cache"), help="bar cache dir"
    )
    parser.add_argument(
        "--champion-only",
        action="store_true",
        help="hold each spec at its factory-selected champion (fast); vary only cost",
    )
    args = parser.parse_args(argv)

    cache_dir = Path(args.cache_dir)
    specs = _select(default_registry(), args.symbol, args.family, args.interval)
    if not specs:
        print("No specs match the given filters.")
        return 1

    mode = "champion-only" if args.champion_only else "full-grid"
    print(f"Decomposing cost drag ({mode}) for {len(specs)} spec(s) against {cache_dir}\n")
    rows: list[dict] = []
    for i, spec in enumerate(specs, 1):
        print(f"[{i}/{len(specs)}] {spec.label} ...", flush=True)
        try:
            rows.append(analyze_spec(spec, cache_dir, champion_only=args.champion_only))
        except Exception as exc:  # noqa: BLE001 -- one bad spec must not kill the run
            print(f"  [ERROR] {spec.label}: {exc}")
            rows.append(
                {
                    "label": spec.label,
                    "symbol": spec.symbol,
                    "family": spec.family,
                    "interval": spec.interval,
                    "classification": "ERROR",
                    "error": str(exc),
                    "gross_pf_ci_lower": 0.0,
                    "net_pf_ci_lower": 0.0,
                    "cost_drag_pf": 0.0,
                    "gross_oos_trades": 0,
                    "net_oos_trades": 0,
                }
            )

    rows.sort(key=lambda r: -r.get("gross_pf_ci_lower", 0.0))
    print(f"\n{'=' * 70}\nCOST-DRAG DECOMPOSITION\n{'=' * 70}")
    print(_format_report(rows))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "threshold": GATE_PF_CI_LOWER,
        "zero_cost": ZERO_COST,
        "realistic_cost": REALISTIC_COST,
        "n_specs": len(rows),
        "rows": rows,
    }
    (REPORT_DIR / "COST_DRAG_REPORT.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nReport -> {REPORT_DIR / 'COST_DRAG_REPORT.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
