"""
JARVIS TRADER — MGC 1d Paper Trading Configuration
====================================================
Walk-Forward Validated: WFE=0.27 (static; adaptive showed identical performance)
Cleared for paper trading: 2026-03-29

Walk-forward analysis (2026-03-29):
- regime_filter=ON is ANTI-PREDICTIVE for gold daily — disabling improves OOS performance.
- adaptive_regime showed identical WFE (0.27) to static — adds complexity with no benefit.
- Static params without regime filter are the correct baseline for paper trading.

Source: engine/backtest/results/EXECUTIVE_BRIEFING.md v2.2
"""

MGC_PAPER_CONFIG = {
    # ── Instrument ────────────────────────────────────────────────────────
    "symbol": "MGC",
    "interval": "1d",
    "enabled": True,

    # ── Capital & Sizing ──────────────────────────────────────────────────
    "initial_capital": 25_000.0,      # Micro gold: lower capital requirement
    "risk_per_trade": 0.0025,         # 0.25% risk (conservative, per exec briefing)

    # ── Strategy Mode ─────────────────────────────────────────────────────
    "regime_filter": False,           # OFF: regime_filter is anti-predictive for gold daily
    "adaptive_regime": False,         # OFF: adaptive WFE identical to static (0.27); extra complexity, zero benefit
    "volume_filter": False,           # Off for daily (volume data less reliable daily)

    # ── STC Signal Parameters (Walk-Forward Validated) ────────────────────
    "sic_params": {
        "stc_os": 15,                 # Oversold threshold
        "stc_ob": 83,                 # Overbought threshold
        "stop_atr_mult": 0.30,        # Stop loss in ATR multiples
        "t1_atr_mult": 1.00,          # Target 1 in ATR multiples
    },

    # ── Kill Thresholds (Safety Gates) ────────────────────────────────────
    # Halt paper trading if first 3 months are ALL negative — tighter early-stage gate.
    "kill_threshold": {
        "consecutive_months_underperform": 3,
        "monthly_underperform_vs_is_pct": 0.50,  # >50% below IS baseline triggers kill
        "rolling_wfe_minimum": 0.15,              # Stop if WFE drops below 0.15
        "halt_if_first_n_months_negative": 3,     # Halt immediately if first 3 calendar months all negative
    },

    # ── Contract Specifications ───────────────────────────────────────────
    "multiplier": 10.0,               # $10/point for MGC (10 oz gold)
    "tick_size": 0.10,                # Minimum price increment
    "commission_per_contract": 2.50,   # Round-trip commission estimate
    "slippage_ticks": 1,              # Conservative 1-tick slippage assumption
}
