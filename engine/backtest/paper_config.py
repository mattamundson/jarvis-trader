"""
JARVIS TRADER — Paper Trading Configuration (v2.7)
===================================================
Approved instruments (as of 2026-03-30):
  MCL 1h: WFE=0.82 EXCELLENT — static params, regime_filter=ON, adaptive=OFF
  MNQ 1h: WFE=0.57 GOOD — adaptive_regime=ON only (MTF and volume filters REJECTED)

Halted:
  MGC 1d: WFE=0.14 OVERFIT — suspended indefinitely

Source: PAPER_TRADING_APPROVAL.md, EXECUTIVE_BRIEFING.md v2.7
"""

MCL_PAPER_CONFIG = {
    # ── Instrument ────────────────────────────────────────────────────────
    "symbol": "MCL",
    "interval": "1h",
    "enabled": True,  # WFE=0.82 EXCELLENT — APPROVED
    # ── Capital & Sizing ──────────────────────────────────────────────────
    "initial_capital": 25_000.0,
    "risk_per_trade": 0.0025,  # 0.25% risk (conservative)
    # ── Strategy Mode ─────────────────────────────────────────────────────
    "regime_filter": True,   # ON: oil is regime-sensitive
    "adaptive_regime": False,  # OFF: adaptive WFE=-0.31 — WORSE than static 0.82
    "volume_filter": False,  # OFF: not tested for MCL
    "mtf_filter": False,     # OFF: not tested for MCL
    # ── STC Signal Parameters (Walk-Forward Validated) ────────────────────
    "sic_params": {
        "stc_os": 15,
        "stc_ob": 83,
        "stop_atr_mult": 0.90,
        "t1_atr_mult": 1.50,
        "t2_atr_mult": 2.618,
        "t3_atr_mult": 4.00,
    },
    # ── Kill Thresholds ────────────────────────────────────────────────────
    "kill_threshold": {
        "consecutive_losses": 3,
        "consecutive_months_underperform": 3,
        "monthly_loss_pct": -0.03,   # -3% monthly triggers halt
        "max_daily_loss": -0.02,
        "rolling_wfe_minimum": 0.40,
    },
    # ── Contract Specifications ───────────────────────────────────────────
    "multiplier": 100.0,  # $100/point for MCL (1000 barrels × $0.10 tick)
    "tick_size": 0.01,
    "commission_per_contract": 2.50,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

MNQ_PAPER_CONFIG = {
    # ── Instrument ────────────────────────────────────────────────────────
    "symbol": "MNQ",
    "interval": "1h",
    "enabled": True,  # WFE=0.57 GOOD — APPROVED (adaptive regime only)
    # ── Capital & Sizing ──────────────────────────────────────────────────
    "initial_capital": 25_000.0,
    "risk_per_trade": 0.0025,  # 0.25% risk
    # ── Strategy Mode ─────────────────────────────────────────────────────
    "regime_filter": True,    # ON: required for adaptive_regime to work
    "adaptive_regime": True,   # ON: lifts WFE 0.24→0.57 — CRITICAL
    "volume_filter": False,   # OFF: HURTS WFE (0.57→-0.23) — NEVER ENABLE
    "mtf_filter": False,      # OFF: HURTS WFE (0.57→0.17) — NEVER ENABLE
    # ── STC Signal Parameters (Walk-Forward Validated) ────────────────────
    "sic_params": {
        "stc_os": 15,
        "stc_ob": 92,
        "stop_atr_mult": 0.70,
        "t1_atr_mult": 1.00,
        "t2_atr_mult": 1.80,
        "t3_atr_mult": 2.618,
    },
    # ── Kill Thresholds ────────────────────────────────────────────────────
    "kill_threshold": {
        "consecutive_losses": 3,
        "consecutive_months_underperform": 3,
        "monthly_loss_pct": -0.03,   # -3% monthly triggers halt
        "max_daily_loss": -0.02,
        "rolling_wfe_minimum": 0.30,
    },
    # ── Contract Specifications ───────────────────────────────────────────
    "multiplier": 2.0,    # $2/point for MNQ (Micro Nasdaq)
    "tick_size": 0.25,
    "commission_per_contract": 2.50,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

MGC_PAPER_CONFIG = {
    # ── Instrument ────────────────────────────────────────────────────────
    "symbol": "MGC",
    "interval": "1d",
    "enabled": False,  # HALTED — WFE=0.14 OVERFIT (below 0.30 threshold)
    # ── Capital & Sizing ──────────────────────────────────────────────────
    "initial_capital": 25_000.0,  # Micro gold: lower capital requirement
    "risk_per_trade": 0.0025,  # 0.25% risk (conservative, per exec briefing)
    # ── Strategy Mode ─────────────────────────────────────────────────────
    "regime_filter": False,  # OFF: regime_filter is anti-predictive for gold daily
    "adaptive_regime": False,  # OFF: adaptive WFE identical to static (0.27); extra complexity, zero benefit
    "volume_filter": False,  # Off for daily (volume data less reliable daily)
    # ── STC Signal Parameters (Walk-Forward Validated) ────────────────────
    "sic_params": {
        "stc_os": 15,  # Oversold threshold
        "stc_ob": 83,  # Overbought threshold
        "stop_atr_mult": 0.30,  # Stop loss in ATR multiples
        "t1_atr_mult": 1.00,  # Target 1 in ATR multiples
    },
    # ── Kill Thresholds (Safety Gates) ────────────────────────────────────
    # Halt paper trading if first 3 months are ALL negative — tighter early-stage gate.
    "kill_threshold": {
        "consecutive_months_underperform": 3,
        "monthly_underperform_vs_is_pct": 0.50,  # >50% below IS baseline triggers kill
        "rolling_wfe_minimum": 0.15,  # Stop if WFE drops below 0.15
        "halt_if_first_n_months_negative": 3,  # Halt immediately if first 3 calendar months all negative
    },
    # ── Contract Specifications ───────────────────────────────────────────
    "multiplier": 10.0,  # $10/point for MGC (10 oz gold)
    "tick_size": 0.10,  # Minimum price increment
    "commission_per_contract": 2.50,  # Round-trip commission estimate
    "slippage_ticks": 1,  # Conservative 1-tick slippage assumption
}
