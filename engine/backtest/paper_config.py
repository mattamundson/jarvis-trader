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
    "enabled": False,  # 2026-05-07: MCL hypotheses A-E exhausted; in DO_NOT_TRADE_SYMBOLS
    #  Capital & Sizing
    "initial_capital": 10_000.0,
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
    "commission_per_contract": 0.85,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

MNQ_PAPER_CONFIG = {
    #  Instrument
    "symbol": "MNQ",
    "interval": "1h",
    "enabled": False,  # 2026-05-07: MNQ trend/breakout/ORB all FAIL gate v2; in DO_NOT_TRADE_SYMBOLS. The 55 trades / 0 wins on 2026-05-06/07 came from this config firing despite the verdict gate; disabling at config layer ensures sync with verdict layer.
    #  Capital & Sizing
    "initial_capital": 10_000.0,
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
    "commission_per_contract": 0.62,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

MGC_PAPER_CONFIG = {
    #  Instrument — SMA(50,120) trend-following, 1h bars
    #  DISABLED 2026-06-26: config<->verdict desync. This block was authorized off
    #  MGC_trend_rank4 "PASS via ALT (2026-05-06)", but rank4 was re-run 2026-06-24
    #  and is now FAIL (p_edge=0.60, fixed_params_min_pf=1.179, mc_95th_dd=4.011% >
    #  4.0% alt ceiling). Its dsr=1.0 was also the degenerate-variance fallback
    #  (fixed af35329). Re-enable only when a fresh rank4 verdict PASSes honestly.
    #  Verdict file: engine/data/gate_v2_verdicts/MGC_trend_rank4.json
    #  WFO champion params: SMA(fast=50, slow=120, atr_trail_mult=2.0)
    "symbol": "MGC",
    "interval": "1h",
    "strategy": "sma_trend",  # Routes to generate_instrument_signals() → trend_signals path
    "enabled": False,  # 2026-06-26: rank4 re-run FAILs gate v2; was enabled on a stale 2026-05-06 PASS
    #  Capital & Sizing
    "initial_capital": 50_000.0,  # ALT routing requires $50K+ account for DD ceiling compliance
    "risk_per_trade": 0.0025,  # 0.25% risk per trade
    #  Strategy Mode — SMA trend uses its own param block
    "regime_filter": False,
    "adaptive_regime": False,
    "composite": False,
    "volume_filter": False,
    "mtf_filter": False,
    #  SMA Trend Parameters (walk-forward champion from WFO rank4)
    "sma_params": {
        "fast": 50,
        "slow": 120,
        "atr_trail_mult": 2.0,
    },
    #  Kill Thresholds — calibrated to ALT routing 7% MC DD ceiling
    "kill_threshold": {
        "consecutive_losses": 4,
        "consecutive_months_underperform": 2,
        "monthly_loss_pct": -0.04,
        "max_daily_loss": -0.02,
        "rolling_wfe_minimum": 0.40,
    },
    #  Contract Specifications
    "multiplier": 10.0,  # $10/point for MGC (Micro Gold, 10 oz)
    "tick_size": 0.10,
    "commission_per_contract": 0.85,
    "slippage_ticks": 2,
    "max_concurrent_positions": 1,
    # Allow entry up to N bars after a crossover to catch signals missed while runner
    # polls between 1h bar closes.  Enters at current-bar close, uses signal-bar levels.
    "signal_lookback_bars": 2,
}

MCL_15M_CONFIG = {
    #  Instrument (15-minute timeframe)
    "symbol": "MCL",
    "interval": "15m",
    "enabled": False,  # 2026-05-07: MCL parked at all timeframes; in DO_NOT_TRADE_SYMBOLS
    #  Capital & Sizing
    "initial_capital": 10_000.0,
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
    "commission_per_contract": 0.85,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

MNQ_15M_CONFIG = {
    #  Instrument (15-minute timeframe)
    "symbol": "MNQ",
    "interval": "15m",
    "enabled": False,  # 2026-05-07: params explicitly say "need WF validation before live"; not validated; in DO_NOT_TRADE_SYMBOLS
    #  Capital & Sizing
    "initial_capital": 10_000.0,
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
    "commission_per_contract": 0.62,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

MES_TREND_PAPER_CONFIG = {
    #  Instrument — SMA(50,200)+RV9 trend-following, 1h bars
    #  Gate v2 verdict: INSUFFICIENT_SAMPLE (2026-06-04) -- rank2 re-run with correct trade-level
    #  metrics shows mc_95th_dd=2.65% (was 1.53% on window-level), alt gate PASSES on all 5 criteria
    #  but GATE_V2_ENFORCE_SAMPLE_ADEQUACY=True in .env triggers INSUFFICIENT_SAMPLE (16 OOS < 30 floor).
    #  Verdict file: engine/data/gate_v2_verdicts/MES_trend_rv_filter_rank2.json
    #  To re-authorize: collect 30+ OOS trades OR set GATE_V2_ENFORCE_SAMPLE_ADEQUACY=False (Amo-gated).
    #  rank11 verdict also INSUFFICIENT_SAMPLE (same 16 OOS < 30 floor).
    #  WFO champion params: SMA(fast=50, slow=200, atr_trail_mult=2.0, min_rv_annualized=9.0)
    #  rank2 grid [50,55,60]x[200]x[2.0] with RV>=9% filter: PF=[1.46,1.86,2.32] (22/22/16 trades)
    #  RV filter: activated via MES_MIN_RV_ANNUALIZED=9.0 in engine/.env (env var path in signals.py)
    "symbol": "MES",
    "interval": "1h",
    "strategy": "sma_trend",  # Routes to generate_instrument_signals() -> trend_signals path
    "enabled": True,  # gate_v2_policy blocks trades (INSUFFICIENT_SAMPLE); runner still polls for data
    #  Capital & Sizing
    "initial_capital": 50_000.0,  # ALT routing requires $50K+ account for DD ceiling compliance
    "risk_per_trade": 0.0025,  # 0.25% risk per trade
    #  Strategy Mode — SMA trend uses its own param block, not STC params
    "regime_filter": False,  # SMA crossover IS the regime filter; external filter redundant
    "adaptive_regime": False,
    "composite": False,
    "volume_filter": False,
    "mtf_filter": False,
    #  SMA Trend Parameters (walk-forward champion from WFO rank2 rv_filter)
    "sma_params": {
        "fast": 50,
        "slow": 200,
        "atr_trail_mult": 2.0,
        "min_rv_annualized": 9.0,  # active via MES_MIN_RV_ANNUALIZED env var; validated in rank2
    },
    #  Kill Thresholds -- calibrated to ALT routing 7% MC DD ceiling
    "kill_threshold": {
        "consecutive_losses": 4,  # SMA trend has lower win rate (~44%) -- allow longer runs
        "consecutive_months_underperform": 2,
        "monthly_loss_pct": -0.04,  # Slightly wider than STC strategies (higher R:R profile)
        "max_daily_loss": -0.02,
        "rolling_wfe_minimum": 0.40,
    },
    #  Contract Specifications
    "multiplier": 5.0,  # $5/point for MES (Micro E-mini S&P 500)
    "tick_size": 0.25,
    "commission_per_contract": 0.62,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
    # Allow entry up to N bars after a crossover to catch signals missed while runner
    # polls between 1h bar closes.  Enters at current-bar close, uses signal-bar levels.
    "signal_lookback_bars": 2,
}

MES_15M_CONFIG = {
    #  Instrument (15-minute timeframe)
    "symbol": "MES",
    "interval": "15m",
    "enabled": False,  # Halted at 1h (WFE=0.09) — 15m pending validation
    #  Capital & Sizing
    "initial_capital": 10_000.0,
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
    "commission_per_contract": 0.62,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
}

MES_VA30_CONFIG = {
    #  Pseudo-symbol -- Value-Area re-entry (candidate sd-116), 30-minute bars.
    #  Actually trades the real MES instrument (see UNDERLYING_INSTRUMENT
    #  below); registered under this synthetic key so it can run alongside
    #  MES_TREND_PAPER_CONFIG without the two strategies colliding in
    #  PAPER_CONFIGS (currently one entry per real symbol).
    #  Gate v2 verdict: PASS (2026-07, ALT) -- 49 OOS trades/4mo, pf_ci_lower=1.19,
    #  dsr=1.0, survives the catastrophic cost-sweep tier (PF=1.5054).
    #  Verdict file is under the REAL symbol "MES" (sd-116's own verdict JSON has
    #  "symbol": "MES") -- verdict_symbol below overrides the gate v2 lookup so
    #  is_ungate_eligible()/is_strategy_authorized() find it under the pseudo-symbol.
    #  Source: engine/backtest/research_candidates/run_value_area_reentry_sd116.py
    "symbol": "MES_VA30",
    "interval": "30m",
    "strategy": "va_reentry",  # Routes to generate_instrument_signals() -> signals_va_reentry path
    "verdict_symbol": "MES",  # gate v2 verdict lookup override -- see gate_v2_policy.py
    "enabled": True,
    #  Capital & Sizing
    "initial_capital": 50_000.0,  # ALT routing, matches sd-116's own backtest capital convention
    "risk_per_trade": 0.0025,  # 0.25% risk per trade
    #  Strategy Mode -- VA re-entry uses its own param block, not STC/SMA params
    "regime_filter": False,
    "adaptive_regime": False,
    "composite": False,
    "volume_filter": False,
    "mtf_filter": False,
    #  VA re-entry parameters (IS-selected champion from the research script's grid)
    "va_reentry_params": {
        "stop_atr_mult": 1.0,
    },
    #  Kill Thresholds -- calibrated to ALT routing DD ceiling
    "kill_threshold": {
        "consecutive_losses": 4,
        "consecutive_months_underperform": 2,
        "monthly_loss_pct": -0.04,
        "max_daily_loss": -0.02,
        "rolling_wfe_minimum": 0.40,
    },
    #  Contract Specifications -- same real instrument as MES_TREND_PAPER_CONFIG
    "multiplier": 5.0,  # $5/point for MES (Micro E-mini S&P 500)
    "tick_size": 0.25,
    "commission_per_contract": 0.62,
    "slippage_ticks": 1,
    "max_concurrent_positions": 1,
    # sd-116 fires exactly on the event bar (2nd consecutive above/below-VA
    # close) -- unlike a slow-moving SMA crossover, a stale signal a few bars
    # late is a different (untested) entry, so lookback is kept minimal.
    "signal_lookback_bars": 1,
}

#  Active paper trading instruments
PAPER_CONFIGS = {
    "MCL": MCL_PAPER_CONFIG,
    "MNQ": MNQ_PAPER_CONFIG,
    "MGC": MGC_PAPER_CONFIG,
    "MES": MES_TREND_PAPER_CONFIG,
    "MES_VA30": MES_VA30_CONFIG,
}

#  Pseudo-symbol -> real underlying instrument, for risk-aggregation purposes
#  only (contract-limit and correlation checks). PAPER_CONFIGS is keyed one
#  entry per symbol; when a second strategy is later registered on an
#  instrument that already has one (e.g. a synthetic "MES_VA30" key alongside
#  the real "MES" trend strategy, both actually trading MES futures), that
#  registration MUST be added here too so combined real-instrument exposure
#  is correctly aggregated rather than tracked/capped independently per key.
UNDERLYING_INSTRUMENT: dict[str, str] = {
    "MES_VA30": "MES",
}


def resolve_underlying(symbol: str) -> str:
    """Return the real underlying futures instrument for *symbol*, for risk
    aggregation. Defaults to the symbol itself; only pseudo-symbols
    registered in UNDERLYING_INSTRUMENT (multiple strategies sharing one
    real instrument) resolve to something different."""
    return UNDERLYING_INSTRUMENT.get(symbol.upper(), symbol.upper())

#  15-minute configs (intraday scanner)
FIFTEEN_MIN_CONFIGS = {
    "MCL": MCL_15M_CONFIG,
    "MNQ": MNQ_15M_CONFIG,
    "MES": MES_15M_CONFIG,
}

ACTIVE_INSTRUMENTS = [sym for sym, cfg in PAPER_CONFIGS.items() if cfg.get("enabled", False)]
