"""
Signal Quality Analyzer — measures how well STC oscillator signals
translate into profitable trades during the paper validation.

STC params from config.py:
  - OS (oversold): 15
  - OB (overbought): 83
  - ATR multiplier (stop): 0.70x
"""

from dataclasses import dataclass, field


@dataclass
class SignalMetrics:
    """Metrics for a set of signals (overall, by symbol, or by regime)."""

    total_signals: int
    profitable_signals: int
    accuracy: float  # profitable / total (0.0 to 1.0)
    avg_signal_to_entry_minutes: float
    avg_entry_to_peak_minutes: float
    avg_pnl_per_signal: float
    best_time_of_day: str  # "10:00-11:00" etc
    worst_time_of_day: str


@dataclass
class SignalQualityReport:
    """Complete signal quality analysis across all symbols and regimes."""

    overall: SignalMetrics
    by_symbol: dict[str, SignalMetrics] = field(default_factory=dict)
    by_regime: dict[str, SignalMetrics] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)


def analyze_signal_quality(trades: list[dict], signals: list[dict] = None) -> SignalQualityReport:
    """
    Analyze signal-to-trade conversion quality.

    Args:
        trades: List of trade dicts with keys:
                - entry_time (datetime)
                - exit_time (datetime)
                - entry_price (float)
                - exit_price (float)
                - symbol (str)
                - regime (str, optional)
        signals: List of signal dicts (optional, for future use)

    Returns:
        SignalQualityReport with overall, per-symbol, per-regime metrics
    """
    if not trades:
        empty_metrics = SignalMetrics(
            total_signals=0,
            profitable_signals=0,
            accuracy=0.0,
            avg_signal_to_entry_minutes=0.0,
            avg_entry_to_peak_minutes=0.0,
            avg_pnl_per_signal=0.0,
            best_time_of_day="N/A",
            worst_time_of_day="N/A",
        )
        return SignalQualityReport(overall=empty_metrics)

    # Overall metrics
    total_signals = len(trades)
    profitable_trades = [t for t in trades if t.get("exit_price", 0) > t.get("entry_price", 0)]
    profitable_signals = len(profitable_trades)
    accuracy = profitable_signals / total_signals if total_signals > 0 else 0.0

    # PnL per signal
    pnls = []
    for trade in trades:
        entry = trade.get("entry_price", 0)
        exit_val = trade.get("exit_price", 0)
        if entry > 0:
            pnl = exit_val - entry
            pnls.append(pnl)
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0

    # Time metrics
    signal_to_entry_minutes = []
    entry_to_peak_minutes = []

    for trade in trades:
        # Signal to entry: assume signal_time or use entry_time
        signal_time = trade.get("signal_time", trade.get("entry_time"))
        entry_time = trade.get("entry_time")
        if signal_time and entry_time:
            delta = (entry_time - signal_time).total_seconds() / 60
            signal_to_entry_minutes.append(max(0, delta))  # Clamp to 0 if negative

        # Entry to peak: use exit_time as proxy for peak
        exit_time = trade.get("exit_time")
        if entry_time and exit_time:
            delta = (exit_time - entry_time).total_seconds() / 60
            entry_to_peak_minutes.append(max(0, delta))

    avg_signal_to_entry = (
        sum(signal_to_entry_minutes) / len(signal_to_entry_minutes)
        if signal_to_entry_minutes
        else 0.0
    )
    avg_entry_to_peak = (
        sum(entry_to_peak_minutes) / len(entry_to_peak_minutes) if entry_to_peak_minutes else 0.0
    )

    # Time-of-day analysis
    best_tof, worst_tof = _calculate_time_of_day_performance(trades)

    overall = SignalMetrics(
        total_signals=total_signals,
        profitable_signals=profitable_signals,
        accuracy=accuracy,
        avg_signal_to_entry_minutes=avg_signal_to_entry,
        avg_entry_to_peak_minutes=avg_entry_to_peak,
        avg_pnl_per_signal=avg_pnl,
        best_time_of_day=best_tof,
        worst_time_of_day=worst_tof,
    )

    # Per-symbol metrics
    by_symbol = {}
    symbols = {t.get("symbol", "UNKNOWN") for t in trades}
    for symbol in symbols:
        symbol_trades = [t for t in trades if t.get("symbol") == symbol]
        symbol_metrics = _compute_metrics_for_trades(symbol_trades)
        by_symbol[symbol] = symbol_metrics

    # Per-regime metrics
    by_regime = {}
    regimes = {t.get("regime", "UNKNOWN") for t in trades if t.get("regime")}
    for regime in regimes:
        regime_trades = [t for t in trades if t.get("regime") == regime]
        regime_metrics = _compute_metrics_for_trades(regime_trades)
        by_regime[regime] = regime_metrics

    # Generate recommendations
    recommendations = _generate_recommendations(
        SignalQualityReport(
            overall=overall, by_symbol=by_symbol, by_regime=by_regime, recommendations=[]
        )
    )

    return SignalQualityReport(
        overall=overall, by_symbol=by_symbol, by_regime=by_regime, recommendations=recommendations
    )


def _compute_metrics_for_trades(trades: list[dict]) -> SignalMetrics:
    """Helper to compute metrics for a filtered list of trades."""
    if not trades:
        return SignalMetrics(
            total_signals=0,
            profitable_signals=0,
            accuracy=0.0,
            avg_signal_to_entry_minutes=0.0,
            avg_entry_to_peak_minutes=0.0,
            avg_pnl_per_signal=0.0,
            best_time_of_day="N/A",
            worst_time_of_day="N/A",
        )

    total = len(trades)
    profitable = len([t for t in trades if t.get("exit_price", 0) > t.get("entry_price", 0)])
    accuracy = profitable / total if total > 0 else 0.0

    pnls = [
        t.get("exit_price", 0) - t.get("entry_price", 0)
        for t in trades
        if t.get("entry_price", 0) > 0
    ]
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0

    signal_to_entry_minutes = []
    entry_to_peak_minutes = []

    for trade in trades:
        signal_time = trade.get("signal_time", trade.get("entry_time"))
        entry_time = trade.get("entry_time")
        if signal_time and entry_time:
            delta = (entry_time - signal_time).total_seconds() / 60
            signal_to_entry_minutes.append(max(0, delta))

        exit_time = trade.get("exit_time")
        if entry_time and exit_time:
            delta = (exit_time - entry_time).total_seconds() / 60
            entry_to_peak_minutes.append(max(0, delta))

    avg_signal_to_entry = (
        sum(signal_to_entry_minutes) / len(signal_to_entry_minutes)
        if signal_to_entry_minutes
        else 0.0
    )
    avg_entry_to_peak = (
        sum(entry_to_peak_minutes) / len(entry_to_peak_minutes) if entry_to_peak_minutes else 0.0
    )

    best_tof, worst_tof = _calculate_time_of_day_performance(trades)

    return SignalMetrics(
        total_signals=total,
        profitable_signals=profitable,
        accuracy=accuracy,
        avg_signal_to_entry_minutes=avg_signal_to_entry,
        avg_entry_to_peak_minutes=avg_entry_to_peak,
        avg_pnl_per_signal=avg_pnl,
        best_time_of_day=best_tof,
        worst_time_of_day=worst_tof,
    )


def _calculate_time_of_day_performance(trades: list[dict]) -> tuple[str, str]:
    """
    Find best and worst trading hours.

    Returns: (best_hour_range, worst_hour_range) e.g., ("10:00-11:00", "14:00-15:00")
    """
    if not trades:
        return ("N/A", "N/A")

    # Bucket trades into hourly windows
    hourly_performance = {}
    for trade in trades:
        entry_time = trade.get("entry_time")
        if not entry_time:
            continue

        hour = entry_time.hour
        hour_key = f"{hour:02d}:00-{hour:02d}:59"

        if hour_key not in hourly_performance:
            hourly_performance[hour_key] = {"count": 0, "profitable": 0}

        hourly_performance[hour_key]["count"] += 1
        if trade.get("exit_price", 0) > trade.get("entry_price", 0):
            hourly_performance[hour_key]["profitable"] += 1

    if not hourly_performance:
        return ("N/A", "N/A")

    # Calculate win rate per hour
    hourly_winrate = {}
    for hour_key, stats in hourly_performance.items():
        if stats["count"] > 0:
            hourly_winrate[hour_key] = stats["profitable"] / stats["count"]

    best_hour = max(hourly_winrate, key=hourly_winrate.get) if hourly_winrate else "N/A"
    worst_hour = min(hourly_winrate, key=hourly_winrate.get) if hourly_winrate else "N/A"

    return (best_hour, worst_hour)


def _generate_recommendations(report: SignalQualityReport) -> list[str]:
    """Generate actionable tuning recommendations based on signal metrics."""
    recommendations = []

    overall = report.overall
    if overall.total_signals == 0:
        return ["Insufficient data for recommendations."]

    # Accuracy-based recommendations
    if overall.accuracy < 0.45:
        recommendations.append(
            "Low signal accuracy (<45%). Consider widening STC OB threshold (from 83) to reduce false signals."
        )
    elif overall.accuracy > 0.65:
        recommendations.append(
            "Strong signal accuracy (>65%). Current STC parameters are well-tuned."
        )

    # Time-of-day recommendations
    if overall.best_time_of_day != "N/A" and overall.worst_time_of_day != "N/A":
        recommendations.append(
            f"Best trading hour: {overall.best_time_of_day}. Consider focusing entries in this window."
        )
        recommendations.append(
            f"Worst trading hour: {overall.worst_time_of_day}. Consider avoiding this window."
        )

    # Per-symbol divergence
    if report.by_symbol:
        accuracies = [m.accuracy for m in report.by_symbol.values()]
        if accuracies and max(accuracies) - min(accuracies) > 0.30:
            best_symbol = max(report.by_symbol, key=lambda s: report.by_symbol[s].accuracy)
            worst_symbol = min(report.by_symbol, key=lambda s: report.by_symbol[s].accuracy)
            recommendations.append(
                f"Symbol divergence detected: {best_symbol} ({report.by_symbol[best_symbol].accuracy:.1%}) vs "
                f"{worst_symbol} ({report.by_symbol[worst_symbol].accuracy:.1%}). "
                "Consider per-symbol parameter tuning."
            )

    # PnL per signal
    if overall.avg_pnl_per_signal > 0:
        recommendations.append(
            f"Positive avg PnL per signal: ${overall.avg_pnl_per_signal:.2f}. Scale gradually."
        )
    else:
        recommendations.append(
            "Negative avg PnL per signal. Review entry/exit logic before increasing trade frequency."
        )

    return recommendations
