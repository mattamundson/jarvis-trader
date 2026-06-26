"""MES Saty ATR (GO continuation) grid search — auction-family gate-v2 input.

Produces a `mes_saty_search_results.json` with per-trade ledgers so the Saty ATR
signal can be run through the SAME rolling-WF + gate-v2 battery that validated
the MES trend champion, instead of the single-split confluence screen.

Sweeps `target_ratio` (target as an ATR multiple from the session anchor) in GO
(continuation) mode — the chart's Calls>/Puts< trigger-break read. Mirrors the
SATY_TARGET_GRID used in signal_confluence_audit.

Run from engine/:
    .venv/Scripts/python -u -m scripts.mes_saty_search --symbol MES
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from scripts.auction_search_common import run_grid_search, run_signal_bt  # noqa: E402

ATR_TRAIL = 2.0

GRID = {
    "target_ratio": [1.0, 1.5, 2.0],
}


def _run(df, target_ratio: float, spec: dict, symbol: str) -> dict:
    """Generate Saty ATR GO-mode signals at the given target and backtest them."""
    from backtest.saty_atr_signals import generate_saty_atr_signals

    sig = generate_saty_atr_signals(df.copy(), mode="go", target_ratio=target_ratio)
    return run_signal_bt(sig, symbol, ATR_TRAIL, spec)


def _run_combo(df, params: dict, spec: dict, symbol: str) -> dict:
    return _run(df, params["target_ratio"], spec, symbol)


def main() -> int:
    return run_grid_search("saty", GRID, _run_combo)


if __name__ == "__main__":
    sys.exit(main())
