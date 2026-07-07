"""
Alert threshold configuration for the JARVIS AlertManager.

These values control when push alerts fire during a trading session.
Adjust here without touching AlertManager logic.
"""

ALERT_THRESHOLDS: dict[str, float] = {
    # Daily loss alerts (as fraction of portfolio equity — negative means loss)
    "daily_loss_25pct": -0.005,   # -0.5% of equity — early warning
    "daily_loss_50pct": -0.010,   # -1.0% of equity — halfway to daily limit
    "daily_loss_75pct": -0.015,   # -1.5% of equity — critical warning (limit is -2%)

    # Peak-to-trough drawdown alerts (negative fraction)
    "drawdown_5pct": -0.05,       # 5% drawdown — elevated risk, watch closely
    "drawdown_10pct": -0.10,      # 10% drawdown — kill switch territory

    # Consecutive trade loss counts (positive integers stored as float for dict uniformity)
    "consecutive_losses_2": 2.0,  # 2 consecutive losses — pattern forming
    "consecutive_losses_3": 3.0,  # 3 consecutive losses — scaling factor kicks in

    # Daily profit alerts (positive fractions — good news)
    "daily_target_50pct": 0.025,  # +2.5% — halfway to daily target
    "daily_target_hit": 0.05,     # +5.0% — daily target achieved, consider de-risking
}
