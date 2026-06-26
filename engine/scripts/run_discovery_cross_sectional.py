"""R3/T14: cross-sectional momentum discovery driver.

Discovers a dollar-neutral long-top / short-bottom basket edge across micro
futures -- a NEW strategy class, orthogonal to the exhausted intraday-simple
class, the pairwise relative-value spreads, and the turn-of-month calendar.

Pipeline per grid combo: load the inner-joined close panel -> portfolio backtest
-> feed the per-period PnL through the SAME gate-v2 evaluation the rest of the
campaign uses (Layer A) -> AND the mandatory chronological H1/H2 split (the
spread campaign proved a pooled bootstrap passes back-loaded non-stationary
edges). A combo is ``promoted`` ONLY if gate-v2 PASS *and* split STRONG.

Isolation: discovery writes ONLY to ``data/discovery_cross_sectional/`` -- never
``data/gate_v2_verdicts/`` (the campaign FDR tree). Copying a promoted verdict in,
pre-registering its lineage, and standing up its dark track is a deliberate,
Amo-gated follow-on (R3/T16), never automatic from a research run.

The grid is small (<=6 combos) on purpose: DSR deflation is honest only when the
number of trials it deflates against equals the number actually tried.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Optional

_ENGINE = Path(__file__).resolve().parents[1]
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from analysis.cross_sectional import load_basket_panel  # noqa: E402
from backtest.xs_portfolio_backtester import (  # noqa: E402
    run_xs_portfolio_backtest,
    temporal_split_verdict,
)
from scripts.validate_strategy import _evaluate_gate_v2, validate  # noqa: E402

OUTPUT_DIR = _ENGINE / "data" / "discovery_cross_sectional"

# Liquid micros spanning equity index (MES/MNQ/M2K/MYM), metals (MGC), energy (MCL)
# -- enough cross-sectional spread for relative momentum to mean something.
DEFAULT_BASKET = ["MES", "MNQ", "M2K", "MYM", "MGC", "MCL"]

# Small grid -> honest DSR n_trials. lookback x top_k = 6 combos.
GRID: dict[str, list] = {"lookback": [10, 20, 40], "top_k": [1, 2]}

HOLD_BARS = 1
CAPITAL = 100_000.0
MIN_TRADES = 30  # gate sample-adequacy floor (MIN_OOS_TRADES_TOTAL)


def iter_grid(grid: Optional[dict] = None) -> list[dict]:
    grid = grid or GRID
    keys = list(grid)
    return [
        dict(zip(keys, vals, strict=True)) for vals in itertools.product(*(grid[k] for k in keys))
    ]


def evaluate_combo(
    panel,
    params: dict,
    n_grid_trials: int,
    cost_bps: float = 2.0,
    n_segments: int = 2,
    n_resamples: int = 10_000,
) -> dict:
    """Backtest one combo, then gate-v2 + chronological split it. Pure (no IO)."""
    lookback = params["lookback"]
    top_k = params["top_k"]
    res = run_xs_portfolio_backtest(
        panel,
        lookback=lookback,
        top_k=top_k,
        hold_bars=HOLD_BARS,
        cost_bps=cost_bps,
        capital=CAPITAL,
    )
    pnls = [t["pnl"] for t in res["trades"]]
    if len(pnls) < MIN_TRADES:
        gate = {
            "verdict": "NO_TRADE",
            "passed_via": None,
            "reason": f"insufficient trades ({len(pnls)} < {MIN_TRADES})",
        }
    else:
        report = validate(
            pnls, n_grid_trials=n_grid_trials, initial_capital=CAPITAL, n_resamples=n_resamples
        )
        gate = _evaluate_gate_v2(report)
    split = temporal_split_verdict(
        panel,
        lookback=lookback,
        top_k=top_k,
        hold_bars=HOLD_BARS,
        cost_bps=cost_bps,
        n_segments=n_segments,
    )
    promoted = gate.get("verdict") == "PASS" and split["verdict"] == "STRONG"
    return {
        "params": params,
        "metrics": {
            k: res[k]
            for k in (
                "total_trades",
                "profit_factor",
                "max_drawdown_pct",
                "sharpe_ratio",
                "total_return_pct",
                "win_rate",
            )
        },
        "gate_verdict": gate,
        "temporal_split": split,
        "promoted": promoted,
    }


def _write_verdict(verdict: dict, out_dir: Optional[str] = None) -> Path:
    out = Path(out_dir) if out_dir else OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / "cross_sectional_discovery.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(verdict, fh, indent=2, default=str)
    return path


def run_discovery(
    symbols: list[str],
    start: str,
    end: str,
    interval: str = "1d",
    cost_bps: float = 2.0,
    loader=None,
) -> dict:
    panel = load_basket_panel(symbols, start, end, interval, loader=loader)
    combos = iter_grid()
    results = [
        evaluate_combo(panel, c, n_grid_trials=len(combos), cost_bps=cost_bps) for c in combos
    ]
    results.sort(key=lambda r: (r["promoted"], r["metrics"]["profit_factor"]), reverse=True)
    return {
        "strategy_class": "cross_sectional_momentum",
        "basket": symbols,
        "start": start,
        "end": end,
        "interval": interval,
        "panel_rows": int(len(panel)),
        "n_combos": len(combos),
        "n_promoted": sum(1 for r in results if r["promoted"]),
        "results": results,
    }


def main() -> None:  # pragma: no cover - CLI glue
    ap = argparse.ArgumentParser(description="Cross-sectional momentum discovery (R3)")
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end", default="2026-03-27")
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--symbols", nargs="*", default=DEFAULT_BASKET)
    ap.add_argument("--cost-bps", type=float, default=2.0)
    args = ap.parse_args()

    verdict = run_discovery(args.symbols, args.start, args.end, args.interval, args.cost_bps)
    path = _write_verdict(verdict)
    print(f"wrote {path}")
    print(
        f"panel_rows={verdict['panel_rows']} combos={verdict['n_combos']} "
        f"promoted={verdict['n_promoted']}"
    )
    if verdict["n_promoted"]:
        print(
            "PROMOTED combo(s) found -> eligible for pre-registration + dark track "
            "(R3/T16, Amo-gated -- NOT auto-registered)."
        )
    else:
        print("No combo cleared gate-v2 AND the chronological split. No promotion.")


if __name__ == "__main__":  # pragma: no cover
    main()
