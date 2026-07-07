"""MES composite (STC+ORB+VWAP) grid search — auction-family gate-v2 input.

Produces a `mes_composite_search_results.json` with per-trade ledgers so the
composite signal can be run through the SAME rolling-WF + gate-v2 battery that
validated the MES trend champion (rolling_wfo_validator → fixed_params_temporal_
validator → cost_sensitivity_sweep → validate_strategy), instead of the
single-split confluence screen.

Sweeps composite's OWN entry gates only — `entry_threshold` (composite score)
and `band_mult` (ORB band width). The STC oversold/overbought levels are NOT
swept: they are Tier-3 canonical params (.claude/rules/backtest-signals.md) and
are left at the symbol defaults inside generate_composite_signals.

Run from engine/:
    .venv/Scripts/python -u -m scripts.mes_composite_search --symbol MES
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from scripts.auction_search_common import run_grid_search, run_signal_bt  # noqa: E402

# Composite carries its own stop/target columns; the trailing-stop ATR multiple
# matches the screen (signal_confluence_audit ran composite at atr_trail=2.0).
ATR_TRAIL = 2.0

GRID = {
    "entry_threshold": [0.45, 0.55, 0.65],
    "band_mult": [2.5, 3.0, 3.5],
}


def _run(df, entry_threshold: float, band_mult: float, spec: dict, symbol: str) -> dict:
    """Generate composite signals at the given params and backtest them."""
    from backtest.composite_signals import generate_composite_signals

    sig = generate_composite_signals(
        df.copy(),
        symbol=symbol,
        entry_threshold=entry_threshold,
        band_mult=band_mult,
    )
    return run_signal_bt(sig, symbol, ATR_TRAIL, spec)


def _run_combo(df, params: dict, spec: dict, symbol: str) -> dict:
    return _run(df, params["entry_threshold"], params["band_mult"], spec, symbol)


def main() -> int:
    return run_grid_search("composite", GRID, _run_combo)


if __name__ == "__main__":
    sys.exit(main())
