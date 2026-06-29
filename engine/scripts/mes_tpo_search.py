"""MES TPO-score grid search — auction-family gate-v2 input.

Produces a `mes_tpo_search_results.json` with per-trade ledgers so the TPO /
value-area read can be run through the SAME rolling-WF + gate-v2 battery that
validated the MES trend champion, instead of the single-split confluence screen.

Sweeps the `enter` (tpo_score crossing threshold) x `stop_mult` (ATR stop)
grid. Reuses `_tpo_contract` from signal_confluence_audit so the TPO entry/stop
construction is identical to the screen — only the evaluation methodology
changes (rolling WF + gate v2 vs. single split).

Run from engine/:
    .venv/Scripts/python -u -m scripts.mes_tpo_search --symbol MES
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from scripts.auction_search_common import run_grid_search, run_signal_bt  # noqa: E402

GRID = {
    "enter": [0.33, 0.50, 0.66],
    "stop_mult": [1.0, 1.5, 2.0],
}


def _run(df, enter: float, stop_mult: float, spec: dict, symbol: str) -> dict:
    """Build the TPO-score contract frame and backtest it.

    The trailing-stop ATR multiple is set to `stop_mult`, matching how the
    screen ran the TPO arm (atr_trail == stop_mult).
    """
    from scripts.signal_confluence_audit import _tpo_contract

    sig = _tpo_contract(df.copy(), enter, stop_mult)
    return run_signal_bt(sig, symbol, stop_mult, spec)


def _run_combo(df, params: dict, spec: dict, symbol: str) -> dict:
    return _run(df, params["enter"], params["stop_mult"], spec, symbol)


def main() -> int:
    return run_grid_search("tpo", GRID, _run_combo)


if __name__ == "__main__":
    sys.exit(main())
