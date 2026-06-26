"""
Strategy C+ Live Signal Runner
==============================
Standalone entry point for generating the weekly live signal.
Runs every Friday at 4:05pm CT via the cron job.

Usage:
    python -m engine.strategy_c.live_signal
    python engine/strategy_c/live_signal.py

CHANGELOG:
  2026-06-17 — Promoted engine_v2 (StrategyCEngineV2) to production.
               Replaces engine.py (v1). 9/10 gates, Sharpe 1.423, OOS CAGR retention 98.6%.
               v1 still importable via from .engine import StrategyCEngine (fallback).
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

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
    # ── v2 engine (production as of 2026-06-17) ───────────────────────────
    from .engine_v2 import StrategyCEngineV2, StrategyCConfigV2

    logger.info("=" * 60)
    logger.info("STRATEGY C+ v2 WEEKLY SIGNAL — %s", datetime.now().strftime("%Y-%m-%d %H:%M CT"))
    logger.info("Engine: StrategyCEngineV2 (9/10 gates, Sharpe 1.423, OOS retention 98.6%)")
    logger.info("=" * 60)

    config = StrategyCConfigV2(
        # Vol targeting
        vol_target=7.0,
        vol_lookback_days=10,
        lookback_long_days=21,
        blend_fast_weight=0.40,
        vol_floor=6.0,
        winsorize_sigma=3.0,
        # VIX composite
        vix_ma_period=26,
        vix_mom_period=4,
        vix_weights=(0.40, 0.25, 0.20, 0.15),
        # Momentum
        mom_lookback_primary=52,
        top_n=2,
        use_factor_tilt=True,
        # T2-6: Enhanced abs mom gate
        use_abs_mom_ma_gate=True,
        ma_breach_weeks=3,
        abs_mom_threshold_bear=0.02,
        # T2-7: Drawdown circuit breaker
        use_drawdown_cb=True,
        dd_tiers=[(0.08, 0.50), (0.15, 0.25)],
        # T3-10: Kalman regime (replaces MTF)
        use_kalman_mtf=True,
        kalman_process_noise=0.5,
        kalman_obs_noise=2.0,
        # T3-11: Min hold
        use_min_hold=True,
        min_hold_weeks=2,
        # T3-12: Risk parity
        use_risk_parity=True,
        risk_parity_lookback=21,
        # Transaction costs
        use_transaction_costs=True,
        execution_mode="moc_friday",
        # Universe (GLD added per T3-13 validation)
        risk_on=["QQQ", "SPY", "EFA", "USMV", "MTUM", "XLK", "XLV", "GLD"],
        risk_off=["IEF", "SHY"],
    )

    engine = StrategyCEngineV2(config=config)

    try:
        signal = engine.get_live_signal()
    except Exception as e:
        logger.error("Signal generation failed (v2): %s", e, exc_info=True)
        # Fallback to v1 on hard failure
        logger.warning("Falling back to v1 engine...")
        try:
            from .engine import StrategyCEngine, StrategyCConfig
            v1_config = StrategyCConfig(
                vol_target=8.0, vol_lookback_days=10, vol_floor=6.0,
                vix_ma_period=26, vix_mom_period=4,
                vix_weights=(0.40, 0.25, 0.20, 0.15),
                mom_lookback_primary=52, top_n=2, use_factor_tilt=True,
                use_macro_filter=True, use_cot=True,
            )
            signal = StrategyCEngine(config=v1_config).get_live_signal()
            signal["_fallback"] = "v1_engine"
            signal["_fallback_reason"] = str(e)
        except Exception as e2:
            logger.error("v1 fallback also failed: %s", e2, exc_info=True)
            return {"error": str(e), "v1_fallback_error": str(e2),
                    "generated_at": datetime.now().isoformat()}

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
    print("  ⚡ STRATEGY C+ WEEKLY SIGNAL")
    print(f"  Generated: {signal.get('generated_at', 'unknown')}")
    print("=" * 60)

    layers = signal.get("layers", {})
    mom = layers.get("momentum_signal", {})
    vol = layers.get("vol_targeting", {})
    vix = layers.get("vix_composite", {})
    macro = layers.get("macro_filter", {})

    print(f"\n  RISK REGIME:     {mom.get('risk_regime', 'UNKNOWN')}")
    print(f"  COMBINED SCALE:  {signal.get('combined_scale', 0):.1%}")

    print(f"\n  ── Signal Layers ──")
    print(f"  Momentum:        {mom.get('risk_regime', '?')} | "
          f"Abs mom pass: {mom.get('absolute_mom_pass', False)}")
    # NOTE: vol_regime = REALIZED vol vs vol-target thresholds (CALM/NORMAL/ELEVATED/CRISIS).
    #       This is NOT the VIX level. Label as RealVolRegime to prevent confusion.
    print(f"  Vol Targeting:   scale={vol.get('scale', 0):.3f} | "
          f"realized_vol={vol.get('realized_vol_pct', 0):.1f}% | "
          f"RealVolRegime={vol.get('vol_regime', '?')}")
    # VIX line: show both vix_regime (raw level band) and composite_regime (position decision)
    fear_spread = vix.get('fear_spread')
    fear_context = vix.get('fear_context', '')
    fear_str = (
        f" | fear_spread={fear_spread:+.2f} ({fear_context})"
        if fear_spread is not None else ""
    )
    print(f"  VIX Composite:   VIX={vix.get('vix', 0):.1f} "
          f"[VIX_LEVEL={vix.get('vix_regime', '?')}] "
          f"[composite={vix.get('composite_regime', '?')}] "
          f"score={vix.get('composite_score', 0):.3f} "
          f"mult={vix.get('position_multiplier', 0):.3f}"
          f"{fear_str}")
    print(f"  Macro Filter:    mult={macro.get('multiplier', 1.0):.3f} | "
          f"yield_curve={macro.get('yield_curve', 'N/A')}")

    print(f"\n  ── Final Holdings ──")
    holdings = signal.get("holdings", {})
    for ticker, weight in sorted(holdings.items(), key=lambda x: -x[1]):
        bar = "█" * int(weight * 20)
        print(f"  {ticker:<6} {weight:.1%}  {bar}")

    print(f"\n  ── IBKR Execution ──")
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
