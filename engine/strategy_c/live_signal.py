"""
Strategy C+ Live Signal Runner
==============================
Standalone entry point for generating the weekly live signal.
Runs every Friday at 4:05pm CT via the cron job.

Usage:
    python -m engine.strategy_c.live_signal
    python engine/strategy_c/live_signal.py
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows — _print_signal_alert and logger calls
# use em-dashes, box-drawing chars, and block chars that fail under cp1252.
# This must run before any print/logging.basicConfig.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("strategy_c_live")


def run_live_signal(
    save_path: str | None = None,
    notify: bool = True,
) -> dict:
    """
    Run the Strategy C+ live signal generator.

    Parameters
    ----------
    save_path : str, optional
        Override output path for live signal JSON
    notify : bool
        Whether to send console alert with signal summary

    Returns
    -------
    dict : Complete live signal
    """
    from .engine import StrategyCConfig, StrategyCEngine

    logger.info("=" * 60)
    logger.info("STRATEGY C+ WEEKLY SIGNAL — %s", datetime.now().strftime("%Y-%m-%d %H:%M CT"))
    logger.info("=" * 60)

    config = StrategyCConfig(
        vol_target=8.0,
        vol_lookback_days=10,
        vol_floor=6.0,
        vix_ma_period=26,
        vix_mom_period=4,
        vix_weights=(0.40, 0.25, 0.20, 0.15),
        mom_lookback_primary=52,
        top_n=2,
        use_factor_tilt=True,
        use_macro_filter=True,
        use_cot=True,
    )

    engine = StrategyCEngine(config=config)

    try:
        signal = engine.get_live_signal()
    except Exception as e:
        logger.error("Signal generation failed: %s", e, exc_info=True)
        return {"error": str(e), "generated_at": datetime.now().isoformat()}

    # Save signal
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)

    signal_path = Path(save_path) if save_path else output_dir / "strategy_c_plus_live_signal.json"
    with open(signal_path, "w") as f:
        json.dump(signal, f, indent=2, default=str)
    logger.info("Signal saved → %s", signal_path)

    # Console notification
    if notify:
        _print_signal_alert(signal)

    return signal


def _print_signal_alert(signal: dict) -> None:
    """Print a human-readable signal alert for the weekly email/dashboard."""
    print("\n" + "=" * 60)
    print("  [*] STRATEGY C+ WEEKLY SIGNAL")
    print(f"  Generated: {signal.get('generated_at', 'unknown')}")
    print("=" * 60)

    layers = signal.get("layers", {})
    mom = layers.get("momentum_signal", {})
    vol = layers.get("vol_targeting", {})
    vix = layers.get("vix_composite", {})
    macro = layers.get("macro_filter", {})

    print(f"\n  RISK REGIME:     {mom.get('risk_regime', 'UNKNOWN')}")
    print(f"  COMBINED SCALE:  {signal.get('combined_scale', 0):.1%}")

    print("\n  ── Signal Layers ──")
    print(f"  Momentum:        {mom.get('risk_regime', '?')} | "
          f"Abs mom pass: {mom.get('absolute_mom_pass', False)}")
    print(f"  Vol Targeting:   scale={vol.get('scale', 0):.3f} | "
          f"realized_vol={vol.get('realized_vol_pct', 0):.1f}% | "
          f"regime={vol.get('vol_regime', '?')}")
    print(f"  VIX Composite:   {vix.get('vix', 0):.1f} | "
          f"regime={vix.get('vix_regime', '?')} | "
          f"score={vix.get('composite_score', 0):.3f} | "
          f"mult={vix.get('position_multiplier', 0):.3f}")
    print(f"  Macro Filter:    mult={macro.get('multiplier', 1.0):.3f} | "
          f"yield_curve={macro.get('yield_curve', 'N/A')}")

    print("\n  ── Final Holdings ──")
    holdings = signal.get("holdings", {})
    for ticker, weight in sorted(holdings.items(), key=lambda x: -x[1]):
        bar = "█" * int(weight * 20)
        print(f"  {ticker:<6} {weight:.1%}  {bar}")

    print("\n  ── IBKR Execution ──")
    ibkr = signal.get("ibkr_instructions", {})
    print(f"  Account: {ibkr.get('account', 'N/A')} ({ibkr.get('mode', 'N/A')})")
    print(f"  Timing:  {ibkr.get('execution_timing', 'N/A')}")
    for order in ibkr.get("orders", []):
        print(f"  ORDER:   {order.get('action', 'BUY')} {order.get('symbol', '?')} "
              f"{order.get('weight_pct', 0):.1f}% — {order.get('order_type', 'MKT')}")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    signal = run_live_signal()
    sys.exit(0 if "error" not in signal else 1)
