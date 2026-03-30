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
    # ── Capital & Sizing ─────────────────────────�