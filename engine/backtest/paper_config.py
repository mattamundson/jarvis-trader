"""
JARVIS TRADER  Paper Trading Configuration (v2.9)
===================================================
Consolidation note (US-303): This module is CONFIGURATION ONLY. No state is
written here. All state management is delegated to PaperTradeTracker.

Approved instruments (as of 2026-04-01):
  MCL 1h: WFE=0.82 EXCELLENT  static params, regime_filter=ON, adaptive=OFF
  MNQ 1h: WFE=0.57 GOOD  adaptive_regime=ON only (MTF and volume filters REJECTED)

Halted:
  MGC 1d: WFE=0.00 (2022-2026 extended, 0/14 valid windows)  CLOSED

Source: PAPER_TRADING_APPROVAL.md, EXECUTIVE_BRIEFING.md v2.9
"""

MCL_PAPER_CONFIG = {
    #  Instrument
    "symbol": "MCL",
    "interval": "1h",
    "enabled": True,  # WFE=0.82 EXCELLENT  APPROVED
    #  Capital & Sizing
    "initial_capital": 25_000.0,
    "risk_per_trade": 0.0025,  # 0.25% risk (conservative)
    #  Strategy Mode
    "regime_filter": True,  # ON: oil is regime-sensitive
    "adaptive_regime": False,  # OFF: adaptive WFE=-0.31  WORSE than static 0.82
    "composite": False,  # Composite STC+ORB+VWAP not validated for MCL (backtest data unavailable in-sandbox)
    "volume_filter": False,  # OFF: not tested for MCL
    "mtf_filter": False,  # OFF: not tested for MCL
    #  STC Signal Parameters (Walk-Forward Validated — Sprint 16 reconciliation)
    #  WF consensus: OS raised 15→23, stop 0.90→0.50, T1 1.50→1.00 (WFE=0.82, OOS PF=1.21)
    "stc_params": {
        "stc_os": 23,
        "stc_ob": 83,
        "stop_atr_mult": 0.50,
        "t1_atr_mult": 1.00,
        "t2_atr_mult": 2.618,
        "t3_atr_mult": 4.00,
    },
    #  Kill Thresholds
    "kill_threshold": {
        "consecutive_losses": 3,
        "consecutive_months_underperform": 3,
        "monthly_loss_pct": -0.03,  # -3% monthly triggers halt
        "max_daily_loss": -0.02,
        "rolling_wfe_minimum": 0.40,
    },
    #  Contract Specifications
    "multiplier": 100.0,  # $100/point for MCL (1000 barrels � $0.10 tick)
    "tick_size": 0.01,
    "commission_per_contract": 2.50,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

MNQ_PAPER_CONFIG = {
    #  Instrument
    "symbol": "MNQ",
    "interval": "1h",
    "enabled": True,  # WFE=0.57 GOOD  APPROVED (adaptive regime only)
    #  Capital & Sizing
    "initial_capital": 25_000.0,
    "risk_per_trade": 0.0025,  # 0.25% risk
    #  Strategy Mode
    "regime_filter": True,  # ON: required for adaptive_regime to work
    "adaptive_regime": True,  # ON: lifts WFE 0.240.57  CRITICAL
    "composite": False,  # Composite STC+ORB+VWAP not validated for MNQ (backtest data unavailable in-sandbox)
    "volume_filter": False,  # OFF: HURTS WFE (0.57-0.23)  NEVER ENABLE
    "mtf_filter": False,  # OFF: HURTS WFE (0.570.17)  NEVER ENABLE
    #  STC Signal Parameters (Walk-Forward Validated)
    "stc_params": {
        "stc_os": 15,
        "stc_ob": 92,
        "stop_atr_mult": 0.70,
        "t1_atr_mult": 1.00,
        "t2_atr_mult": 1.80,
        "t3_atr_mult": 2.618,
    },
    #  Kill Thresholds
    "kill_threshold": {
        "consecutive_losses": 3,
        "consecutive_months_underperform": 3,
        "monthly_loss_pct": -0.03,  # -3% monthly triggers halt
        "max_daily_loss": -0.02,
        "rolling_wfe_minimum": 0.30,
    },
    #  Contract Specifications
    "multiplier": 2.0,  # $2/point for MNQ (Micro Nasdaq)
    "tick_size": 0.25,
    "commission_per_contract": 2.50,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

MGC_PAPER_CONFIG = {
    #  Instrument
    "symbol": "MGC",
    "interval": "1d",
    "enabled": False,  # WFE=0.00 (2022-2026 extended, 0/14 valid windows)  CLOSED (v2.9)
    #  Capital & Sizing
    "initial_capital": 25_000.0,
    "risk_per_trade": 0.0025,
    #  Strategy Mode
    "regime_filter": False,  # OFF: anti-predictive for gold daily
    "adaptive_regime": False,  # OFF: no valid windows even with adaptive
    "volume_filter": False,
    "mtf_filter": False,
    #  STC Signal Parameters (last known, NOT validated  strategy CLOSED)
    "stc_params": {
        "stc_os": 17,
        "stc_ob": 88,
        "stop_atr_mult": 0.30,
        "t1_atr_mult": 1.50,
        "t2_atr_mult": 2.618,
        "t3_atr_mult": 4.00,
    },
    #  Kill Thresholds
    "kill_threshold": {
        "consecutive_losses": 2,
        "consecutive_months_underperform": 1,
        "monthly_loss_pct": -0.02,
        "max_daily_loss": -0.01,
        "rolling_wfe_minimum": 0.50,  # Threshold deliberately high since strategy is closed
    },
    #  Contract Specifications
    "multiplier": 10.0,  # $10/troy oz for MGC (Micro Gold, 10 oz)
    "tick_size": 0.10,
    "commission_per_contract": 2.50,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

MCL_15M_CONFIG = {
    #  Instrument (15-minute timeframe)
    "symbol": "MCL",
    "interval": "15m",
    "enabled": True,  # Enabled for trade frequency validation
    #  Capital & Sizing
    "initial_capital": 25_000.0,
    "risk_per_trade": 0.0025,  # 0.25% risk (conservative)
    #  Strategy Mode
    "regime_filter": True,  # ON: baseline from 1h config
    "adaptive_regime": False,  # OFF: needs walk-forward validation before enabling
    "volume_filter": False,  # OFF: not tested for MCL 15m
    "mtf_filter": False,  # OFF: not tested for MCL 15m
    #  STC Signal Parameters (aligned with MCL_PAPER_CONFIG WF consensus — Sprint 16)
    #  NOTE: 15m timeframe still needs independent WF validation; using 1h consensus as baseline
    "stc_params": {
        "stc_os": 23,
        "stc_ob": 83,
        "stop_atr_mult": 0.50,
        "t1_atr_mult": 1.00,
        "t2_atr_mult": 2.618,
        "t3_atr_mult": 4.00,
    },
    #  Kill Thresholds
    "kill_threshold": {
        "consecutive_losses": 3,
        "consecutive_months_underperform": 3,
        "monthly_loss_pct": -0.03,
        "max_daily_loss": -0.02,
        "rolling_wfe_minimum": 0.40,
    },
    #  Contract Specifications
    "multiplier": 100.0,
    "tick_size": 0.01,
    "commission_per_contract": 2.50,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

MNQ_15M_CONFIG = {
    #  Instrument (15-minute timeframe)
    "symbol": "MNQ",
    "interval": "15m",
    "enabled": True,  # Enabled for trade frequency validation
    #  Capital & Sizing
    "initial_capital": 25_000.0,
    "risk_per_trade": 0.0025,  # 0.25% risk
    #  Strategy Mode
    "regime_filter": True,  # ON: baseline from 1h config
    "adaptive_regime": False,  # OFF: needs walk-forward validation before enabling
    "volume_filter": False,  # OFF: not tested for MNQ 15m
    "mtf_filter": False,  # OFF: not tested for MNQ 15m
    #  STC Signal Parameters (copied from MNQ_PAPER_CONFIG as baseline)
    #  NOTE: These params need walk-forward validation before live use
    "stc_params": {
        "stc_os": 15,
        "stc_ob": 92,
        "stop_atr_mult": 0.70,
        "t1_atr_mult": 1.00,
        "t2_atr_mult": 1.80,
        "t3_atr_mult": 2.618,
    },
    #  Kill Thresholds
    "kill_threshold": {
        "consecutive_losses": 3,
        "consecutive_months_underperform": 3,
        "monthly_loss_pct": -0.03,
        "max_daily_loss": -0.02,
        "rolling_wfe_minimum": 0.30,
    },
    #  Contract Specifications
    "multiplier": 2.0,
    "tick_size": 0.25,
    "commission_per_contract": 2.50,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

MES_15M_CONFIG = {
    #  Instrument (15-minute timeframe)
    "symbol": "MES",
    "interval": "15m",
    "enabled": False,  # Halted at 1h (WFE=0.09) — 15m pending validation
    #  Capital & Sizing
    "initial_capital": 25_000.0,
    "risk_per_trade": 0.0025,  # 0.25% risk
    #  Strategy Mode
    "regime_filter": True,  # ON: baseline for regime-sensitive instruments
    "adaptive_regime": False,  # OFF: needs walk-forward validation before enabling
    "volume_filter": False,  # OFF: not tested for MES 15m
    "mtf_filter": False,  # OFF: not tested for MES 15m
    #  STC Signal Parameters (from last known MES baseline)
    "stc_params": {
        "stc_os": 15,
        "stc_ob": 83,
        "stop_atr_mult": 0.90,
        "t1_atr_mult": 1.50,
        "t2_atr_mult": 2.618,
        "t3_atr_mult": 4.00,
    },
    #  Kill Thresholds
    "kill_threshold": {
        "consecutive_losses": 3,
        "consecutive_months_underperform": 3,
        "monthly_loss_pct": -0.03,
        "max_daily_loss": -0.02,
        "rolling_wfe_minimum": 0.40,
    },
    #  Contract Specifications
    "multiplier": 5.0,  # $5/point for MES (Micro E-mini S&P 500)
    "tick_size": 0.25,
    "commission_per_contract": 2.50,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

#  Active paper trading instruments
PAPER_CONFIGS = {
    "MCL": MCL_PAPER_CONFIG,
    "MNQ": MNQ_PAPER_CONFIG,
    "MGC": MGC_PAPER_CONFIG,
}

#  15-minute configs (intraday scanner)
FIFTEEN_MIN_CONFIGS = {
    "MCL": MCL_15M_CONFIG,
    "MNQ": MNQ_15M_CONFIG,
    "MES": MES_15M_CONFIG,
}

ACTIVE_INSTRUMENTS = [sym for sym, cfg in PAPER_CONFIGS.items() if cfg.get("enabled", False)]
