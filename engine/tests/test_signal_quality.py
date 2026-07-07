"""
Tests for Signal Quality Analyzer.

Covers accuracy, time-of-day analysis, per-symbol breakdown,
empty data handling, and recommendation generation.
"""

from datetime import datetime, timedelta

import pytest

from analytics.signal_quality import (
    SignalMetrics,
    SignalQualityReport,
    analyze_signal_quality,
)


class TestSignalQualityAnalyzer:
    """Test suite for signal quality analysis."""

    def test_empty_trades_returns_empty_report(self):
        """Empty trade list should return zeroed metrics."""
        report = analyze_signal_quality([])

        assert report.overall.total_signals == 0
        assert report.overall.profitable_signals == 0
        assert report.overall.accuracy == 0.0
        assert report.overall.best_time_of_day == "N/A"
        assert len(report.by_symbol) == 0
        assert len(report.by_regime) == 0

    def test_accuracy_calculation(self):
        """Test accuracy (profitable / total) calculation."""
        now = datetime.now()
        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,  # profitable
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
            {
                "entry_price": 100.0,
                "exit_price": 98.0,  # loss
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
        ]

        report = analyze_signal_quality(trades)

        assert report.overall.total_signals == 2
        assert report.overall.profitable_signals == 1
        assert report.overall.accuracy == 0.5

    def test_avg_pnl_per_signal(self):
        """Test average PnL calculation."""
        now = datetime.now()
        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 110.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MCL",
            },
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MCL",
            },
        ]

        report = analyze_signal_quality(trades)

        # (10 + 5) / 2 = 7.5
        assert report.overall.avg_pnl_per_signal == 7.5

    def test_time_of_day_analysis(self):
        """Test best/worst trading hour identification."""
        base = datetime(2026, 4, 2, 10, 0, 0)

        trades = []
        # Morning (10:00): 2/3 profitable
        for i in range(3):
            trades.append(
                {
                    "entry_price": 100.0,
                    "exit_price": 102.0 if i < 2 else 99.0,
                    "entry_time": base + timedelta(minutes=i),
                    "exit_time": base + timedelta(minutes=30 + i),
                    "symbol": "MES",
                }
            )

        # Afternoon (14:00): 1/3 profitable
        base_afternoon = datetime(2026, 4, 2, 14, 0, 0)
        for i in range(3):
            trades.append(
                {
                    "entry_price": 100.0,
                    "exit_price": 102.0 if i == 0 else 99.0,
                    "entry_time": base_afternoon + timedelta(minutes=i),
                    "exit_time": base_afternoon + timedelta(minutes=30 + i),
                    "symbol": "MES",
                }
            )

        report = analyze_signal_quality(trades)

        # 10:00 should be best (2/3), 14:00 should be worst (1/3)
        assert report.overall.best_time_of_day == "10:00-10:59"
        assert report.overall.worst_time_of_day == "14:00-14:59"

    def test_per_symbol_breakdown(self):
        """Test per-symbol metrics calculation."""
        now = datetime.now()

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
            {
                "entry_price": 100.0,
                "exit_price": 95.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MCL",
            },
        ]

        report = analyze_signal_quality(trades)

        assert "MES" in report.by_symbol
        assert "MCL" in report.by_symbol
        assert report.by_symbol["MES"].total_signals == 2
        assert report.by_symbol["MES"].profitable_signals == 2
        assert report.by_symbol["MES"].accuracy == 1.0
        assert report.by_symbol["MCL"].total_signals == 1
        assert report.by_symbol["MCL"].profitable_signals == 0
        assert report.by_symbol["MCL"].accuracy == 0.0

    def test_per_regime_breakdown(self):
        """Test per-regime metrics calculation."""
        now = datetime.now()

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
                "regime": "trending",
            },
            {
                "entry_price": 100.0,
                "exit_price": 102.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
                "regime": "trending",
            },
            {
                "entry_price": 100.0,
                "exit_price": 98.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MCL",
                "regime": "ranging",
            },
        ]

        report = analyze_signal_quality(trades)

        assert "trending" in report.by_regime
        assert "ranging" in report.by_regime
        assert report.by_regime["trending"].total_signals == 2
        assert report.by_regime["trending"].profitable_signals == 2
        assert report.by_regime["trending"].accuracy == 1.0
        assert report.by_regime["ranging"].total_signals == 1
        assert report.by_regime["ranging"].profitable_signals == 0
        assert report.by_regime["ranging"].accuracy == 0.0

    def test_signal_to_entry_timing(self):
        """Test signal-to-entry time calculation."""
        base = datetime(2026, 4, 2, 10, 0, 0)

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "signal_time": base,
                "entry_time": base + timedelta(minutes=5),
                "exit_time": base + timedelta(minutes=30),
                "symbol": "MES",
            },
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "signal_time": base + timedelta(minutes=10),
                "entry_time": base + timedelta(minutes=15),
                "exit_time": base + timedelta(minutes=40),
                "symbol": "MES",
            },
        ]

        report = analyze_signal_quality(trades)

        # (5 + 5) / 2 = 5
        assert report.overall.avg_signal_to_entry_minutes == 5.0

    def test_entry_to_peak_timing(self):
        """Test entry-to-peak (exit) time calculation."""
        base = datetime(2026, 4, 2, 10, 0, 0)

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "entry_time": base,
                "exit_time": base + timedelta(minutes=30),
                "symbol": "MES",
            },
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "entry_time": base + timedelta(minutes=10),
                "exit_time": base + timedelta(minutes=50),
                "symbol": "MES",
            },
        ]

        report = analyze_signal_quality(trades)

        # (30 + 40) / 2 = 35
        assert report.overall.avg_entry_to_peak_minutes == 35.0

    def test_recommendation_generation_low_accuracy(self):
        """Test recommendations for low accuracy scenarios."""
        now = datetime.now()

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 99.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
            {
                "entry_price": 100.0,
                "exit_price": 98.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
            {
                "entry_price": 100.0,
                "exit_price": 97.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
        ]

        report = analyze_signal_quality(trades)

        # Accuracy = 0/3 < 45%
        assert len(report.recommendations) > 0
        assert any("accuracy" in rec.lower() for rec in report.recommendations)

    def test_recommendation_generation_high_accuracy(self):
        """Test recommendations for high accuracy scenarios."""
        now = datetime.now()

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
            {
                "entry_price": 100.0,
                "exit_price": 104.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
            {
                "entry_price": 100.0,
                "exit_price": 103.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
        ]

        report = analyze_signal_quality(trades)

        # Accuracy = 3/3 = 100% > 65%
        assert any("well-tuned" in rec.lower() for rec in report.recommendations)

    def test_recommendation_symbol_divergence(self):
        """Test recommendations for symbol performance divergence."""
        now = datetime.now()

        # MES: 2/2 profitable
        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
        ]

        # MCL: 0/3 profitable
        for _ in range(3):
            trades.append(
                {
                    "entry_price": 100.0,
                    "exit_price": 98.0,
                    "entry_time": now,
                    "exit_time": now + timedelta(minutes=30),
                    "symbol": "MCL",
                }
            )

        report = analyze_signal_quality(trades)

        # Divergence > 30% (1.0 - 0.0 = 1.0)
        assert any("divergence" in rec.lower() for rec in report.recommendations)

    def test_recommendation_positive_pnl(self):
        """Test recommendations for positive average PnL."""
        now = datetime.now()

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "entry_time": now,
                "exit_time": now + timedelta(minutes=30),
                "symbol": "MES",
            },
        ]

        report = analyze_signal_quality(trades)

        assert any("scale gradually" in rec.lower() for rec in report.recommendations)

    def test_missing_signal_time_uses_entry_time(self):
        """Test that missing signal_time falls back to entry_time."""
        base = datetime(2026, 4, 2, 10, 0, 0)

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "entry_time": base,
                "exit_time": base + timedelta(minutes=30),
                "symbol": "MES",
                # No signal_time; should fallback to entry_time
            },
        ]

        report = analyze_signal_quality(trades)

        # signal_to_entry should be ~0 when both use entry_time
        assert report.overall.avg_signal_to_entry_minutes == 0.0

    def test_clamping_negative_timedeltas(self):
        """Test that negative time deltas are clamped to 0."""
        base = datetime(2026, 4, 2, 10, 0, 0)

        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 105.0,
                "signal_time": base + timedelta(minutes=10),
                "entry_time": base,  # signal_time > entry_time (negative delta)
                "exit_time": base + timedelta(minutes=30),
                "symbol": "MES",
            },
        ]

        report = analyze_signal_quality(trades)

        # Should be clamped to 0
        assert report.overall.avg_signal_to_entry_minutes == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
