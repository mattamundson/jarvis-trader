"""
Tests for TiltDetector — behavioral tilt detection system.
All tests are pure in-memory (no DB, no LLM, no broker).
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from risk.tilt_detector import TiltDetector, TiltState

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def detector():
    return TiltDetector()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _record_losses(d: TiltDetector, n: int, symbol: str = "MES") -> None:
    """Record n consecutive stop-out losses."""
    for _ in range(n):
        d.record_trade(symbol, "LONG", 1, 5000.0, pnl=-50.0, is_stop_out=True)


def _record_wins(d: TiltDetector, n: int, symbol: str = "MES") -> None:
    """Record n consecutive wins."""
    for _ in range(n):
        d.record_trade(symbol, "LONG", 1, 5000.0, pnl=50.0)


# ── Baseline / Clean State ────────────────────────────────────────────────────


class TestCleanState:
    def test_no_tilt_initially(self, detector):
        s = detector.check()
        assert not s.is_tilted
        assert s.tilt_score == 0.0
        assert s.position_size_multiplier == 1.0
        assert s.severity == "none"
        assert s.tilt_indicators == []
        assert s.cooldown_until is None

    def test_get_position_multiplier_clean(self, detector):
        assert detector.get_position_multiplier() == 1.0

    def test_get_status_keys(self, detector):
        status = detector.get_status()
        required_keys = [
            "is_tilted",
            "tilt_score",
            "severity",
            "tilt_indicators",
            "position_size_multiplier",
            "cooldown_until",
            "recent_trade_count",
            "consecutive_losses",
            "rapid_trades_30min",
            "recent_vetoes",
        ]
        for key in required_keys:
            assert key in status, f"Missing key: {key}"


# ── Consecutive Loss Indicators ───────────────────────────────────────────────


class TestConsecutiveLosses:
    def test_2_losses_no_tilt(self, detector):
        _record_losses(detector, 2)
        s = detector.check()
        assert not s.is_tilted
        assert s.tilt_score < 0.3

    def test_3_losses_caution(self, detector):
        _record_losses(detector, 3)
        s = detector.check()
        assert s.is_tilted
        assert any("consecutive_losses_3" in i for i in s.tilt_indicators)
        assert s.tilt_score >= 0.2
        assert s.severity == "caution"

    def test_5_losses_warning(self, detector):
        _record_losses(detector, 5)
        s = detector.check()
        assert s.tilt_score >= 0.4
        assert any("consecutive_losses_5" in i for i in s.tilt_indicators)

    def test_7_losses_halt(self, detector):
        _record_losses(detector, 7)
        s = detector.check()
        assert s.position_size_multiplier == 0.0
        assert s.severity == "critical"
        assert s.cooldown_until is not None
        assert s.cooldown_until > datetime.now()

    def test_win_after_loss_resets_consecutive(self, detector):
        _record_losses(detector, 3)
        _record_wins(detector, 1)
        # The TiltDetector's in-memory counter should drop back to 0
        s = detector.check()
        # loss_tracker is None so it uses in-memory count
        assert not any("consecutive_losses_3" in i for i in s.tilt_indicators)


# ── Rapid Trades ──────────────────────────────────────────────────────────────


class TestRapidTrades:
    def test_4_trades_no_rapid_flag(self, detector):
        for _ in range(4):
            detector.record_trade("MES", "LONG", 1, 5000.0, pnl=10.0)
        s = detector.check()
        assert not any("rapid_trades" in i for i in s.tilt_indicators)

    def test_5_trades_in_30min_fires(self, detector):
        for _ in range(6):
            detector.record_trade("MES", "LONG", 1, 5000.0, pnl=10.0)
        s = detector.check()
        assert any("rapid_trades" in i for i in s.tilt_indicators)

    def test_rapid_trades_adds_score(self, detector):
        for _ in range(6):
            detector.record_trade("MES", "LONG", 1, 5000.0, pnl=10.0)
        s = detector.check()
        assert s.tilt_score >= 0.3


# ── Revenge Sizing ────────────────────────────────────────────────────────────


class TestRevengeSizing:
    def test_size_increase_after_loss_detected(self, detector):
        detector.record_trade("MES", "LONG", 1, 5000.0, pnl=-50.0)
        detector.record_trade("MES", "LONG", 2, 5005.0, pnl=None)
        s = detector.check()
        assert "revenge_sizing" in s.tilt_indicators

    def test_no_size_increase_not_detected(self, detector):
        detector.record_trade("MES", "LONG", 2, 5000.0, pnl=-50.0)
        detector.record_trade("MES", "LONG", 1, 5005.0, pnl=None)
        s = detector.check()
        assert "revenge_sizing" not in s.tilt_indicators

    def test_size_increase_after_win_not_revenge(self, detector):
        detector.record_trade("MES", "LONG", 1, 5000.0, pnl=50.0)
        detector.record_trade("MES", "LONG", 2, 5005.0, pnl=None)
        s = detector.check()
        assert "revenge_sizing" not in s.tilt_indicators


# ── Rapid Re-Entry ────────────────────────────────────────────────────────────


class TestRapidReentry:
    def test_reentry_same_symbol_after_stop_detected(self, detector):
        detector.record_trade("MES", "LONG", 1, 5000.0, pnl=-50.0, is_stop_out=True)
        detector.record_trade("MES", "LONG", 1, 5005.0, pnl=None)
        s = detector.check()
        assert "rapid_reentry_after_stop" in s.tilt_indicators

    def test_reentry_different_symbol_not_flagged(self, detector):
        # Record stop-out without adding to _recent_trades (inject directly into _stop_outs)
        # to isolate the rapid-reentry logic from the trade history.
        from datetime import datetime

        detector._stop_outs.append({"timestamp": datetime.now(), "symbol": "MES"})
        detector.record_trade("MNQ", "LONG", 1, 21000.0, pnl=None)
        s = detector.check()
        assert "rapid_reentry_after_stop" not in s.tilt_indicators


# ── Risk Vetoes ───────────────────────────────────────────────────────────────


class TestRiskVetoes:
    def test_1_veto_no_flag(self, detector):
        detector.record_risk_veto()
        s = detector.check()
        assert not any("risk_overrides" in i for i in s.tilt_indicators)

    def test_2_vetoes_flag(self, detector):
        detector.record_risk_veto()
        detector.record_risk_veto()
        s = detector.check()
        assert any("risk_overrides" in i for i in s.tilt_indicators)
        assert s.tilt_score >= 0.2


# ── Drawdown Acceleration ─────────────────────────────────────────────────────


class TestDrawdownAcceleration:
    def test_flat_drawdown_no_flag(self, detector):
        for _ in range(8):
            detector.update_drawdown(2.0)
        s = detector.check()
        assert "drawdown_accelerating" not in s.tilt_indicators

    def test_accelerating_drawdown_flagged(self, detector):
        # First half: small drawdown; second half: 50% larger
        for _ in range(4):
            detector.update_drawdown(2.0)
        for _ in range(4):
            detector.update_drawdown(3.5)
        s = detector.check()
        assert "drawdown_accelerating" in s.tilt_indicators


# ── Severity + Multiplier Mapping ────────────────────────────────────────────


class TestSeverityMapping:
    def test_score_below_0_3_no_tilt(self, detector):
        s = detector.check()
        assert s.severity == "none"
        assert s.position_size_multiplier == 1.0

    def test_score_0_3_to_0_5_caution(self, detector):
        # Use vetoes only to get a clean 0.4 score without stop-out side effects
        for _ in range(3):
            detector.record_risk_veto()  # only 2 needed to fire, but score is 0.2
        # 2 vetoes = +0.2; need a second source — drawdown acceleration
        for _ in range(4):
            detector.update_drawdown(1.0)
        for _ in range(4):
            detector.update_drawdown(1.5)  # 50% increase — flags acceleration +0.2
        # total: 0.2 (vetoes) + 0.2 (drawdown) = 0.4 → caution
        s = detector.check()
        assert s.severity == "caution"
        assert s.position_size_multiplier == 0.75

    def test_score_0_5_to_0_7_warning(self):
        # Use a mock loss_tracker that returns consecutive_losses=3 (+0.2)
        # so we don't pollute _stop_outs via record_trade.
        # Then add vetoes (+0.2) + drawdown acceleration (+0.2) = 0.6 total → warning.
        mock_lt = MagicMock()
        mock_lt.get_consecutive_losses.return_value = 3
        d = TiltDetector(loss_tracker=mock_lt)
        d.record_risk_veto()
        d.record_risk_veto()  # +0.2 vetoes
        for _ in range(4):
            d.update_drawdown(1.0)
        for _ in range(4):
            d.update_drawdown(1.5)  # +0.2 drawdown acceleration
        # total: 0.2 (consecutive) + 0.2 (vetoes) + 0.2 (drawdown) = 0.6 → warning
        s = d.check()
        assert s.severity == "warning"
        assert s.position_size_multiplier == 0.5

    def test_score_0_7_to_0_85_critical_quarter(self, detector):
        _record_losses(detector, 5)  # +0.4
        for _ in range(6):
            detector.record_trade("MES", "LONG", 1, 5000.0, pnl=10.0)  # +0.3 rapid trades
        detector.record_risk_veto()
        detector.record_risk_veto()  # +0.2 → total 0.9 → capped or critical
        s = detector.check()
        # Either critical 0.25 or halted 0.0
        assert s.severity == "critical"
        assert s.position_size_multiplier in (0.0, 0.25)


# ── Cooldown ──────────────────────────────────────────────────────────────────


class TestCooldown:
    def test_cooldown_set_on_7_losses(self, detector):
        _record_losses(detector, 7)
        s = detector.check()
        assert s.cooldown_until is not None
        assert s.cooldown_until > datetime.now()

    def test_cooldown_active_returns_halted_state(self, detector):
        _record_losses(detector, 7)
        _ = detector.check()  # triggers cooldown
        s2 = detector.check()
        assert s2.position_size_multiplier == 0.0
        assert "cooldown_active" in s2.tilt_indicators

    def test_expired_cooldown_clears(self, detector):
        # Manually set a past cooldown
        detector._cooldown_until = datetime.now() - timedelta(seconds=1)
        s = detector.check()
        assert s.cooldown_until is None
        assert detector._cooldown_until is None


# ── Reset ─────────────────────────────────────────────────────────────────────


class TestReset:
    def test_reset_clears_all_state(self, detector):
        _record_losses(detector, 5)
        for _ in range(6):
            detector.record_trade("MES", "LONG", 1, 5000.0, pnl=10.0)
        detector.record_risk_veto()
        detector.record_risk_veto()
        detector.reset()
        s = detector.check()
        assert not s.is_tilted
        assert s.tilt_score == 0.0
        assert s.tilt_indicators == []
        assert detector._cooldown_until is None

    def test_reset_clears_cooldown(self, detector):
        _record_losses(detector, 7)
        detector.check()  # activate cooldown
        detector.reset()
        assert detector._cooldown_until is None


# ── Loss Tracker Integration ──────────────────────────────────────────────────


class TestLossTrackerIntegration:
    def test_uses_loss_tracker_consecutive_count(self):
        mock_lt = MagicMock()
        mock_lt.get_consecutive_losses.return_value = 5
        d = TiltDetector(loss_tracker=mock_lt)
        s = d.check()
        assert any("consecutive_losses_5" in i for i in s.tilt_indicators)
        mock_lt.get_consecutive_losses.assert_called()

    def test_falls_back_to_in_memory_if_loss_tracker_fails(self):
        mock_lt = MagicMock()
        mock_lt.get_consecutive_losses.side_effect = Exception("tracker error")
        d = TiltDetector(loss_tracker=mock_lt)
        # No trades recorded, so in-memory count = 0
        s = d.check()
        assert not s.is_tilted


# ── Safety Layer Integration ──────────────────────────────────────────────────


class TestSafetyLayerIntegration:
    """Verify tilt_detector attribute is correctly wired."""

    def test_safety_layer_has_tilt_detector_attribute(self):
        from risk.safety_layer import SafetyLayer

        class FakeConfig:
            LIVE_TRADING_ENABLED = True
            REQUIRE_HUMAN_APPROVAL = False
            MAX_DAILY_LOSS_PCT = 0.02
            MAX_DRAWDOWN_PCT = 0.10
            MAX_SINGLE_ORDER_VALUE = 50000.0
            MAX_POSITION_SIZE_PCT = 0.25
            MAX_ORDERS_PER_MINUTE = 10
            MAX_CONTRACTS_PER_INSTRUMENT = 5
            MAX_OVERNIGHT_CONTRACTS = 5

        sl = SafetyLayer(FakeConfig())
        assert hasattr(sl, "tilt_detector")
        assert sl.tilt_detector is None

    def test_tilt_detector_injection(self):
        from risk.safety_layer import SafetyLayer

        class FakeConfig:
            LIVE_TRADING_ENABLED = True
            REQUIRE_HUMAN_APPROVAL = False
            MAX_DAILY_LOSS_PCT = 0.02
            MAX_DRAWDOWN_PCT = 0.10
            MAX_SINGLE_ORDER_VALUE = 50000.0
            MAX_POSITION_SIZE_PCT = 0.25
            MAX_ORDERS_PER_MINUTE = 10
            MAX_CONTRACTS_PER_INSTRUMENT = 5
            MAX_OVERNIGHT_CONTRACTS = 5

        sl = SafetyLayer(FakeConfig())
        td = TiltDetector()
        sl.tilt_detector = td
        assert sl.tilt_detector is td

    def test_check_order_blocked_when_tilt_halted(self):
        from risk.safety_layer import OrderRequest, SafetyLayer

        class FakeConfig:
            LIVE_TRADING_ENABLED = True
            REQUIRE_HUMAN_APPROVAL = False
            MAX_DAILY_LOSS_PCT = 0.02
            MAX_DRAWDOWN_PCT = 0.10
            MAX_SINGLE_ORDER_VALUE = 50000.0
            MAX_POSITION_SIZE_PCT = 0.25
            MAX_ORDERS_PER_MINUTE = 10
            MAX_CONTRACTS_PER_INSTRUMENT = 5
            MAX_OVERNIGHT_CONTRACTS = 5

        sl = SafetyLayer(FakeConfig())
        td = TiltDetector()
        _record_losses(td, 7)  # triggers halt
        td.check()  # activate cooldown
        sl.tilt_detector = td

        # estimated_value must be < 25% of portfolio_equity to pass the position-size check
        # 2000 / 100000 = 2% < 25% — well within limit
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=2000.0,
        )
        result = sl.check_order(order, portfolio_equity=100000.0)
        assert not result.approved
        assert "tilt" in result.rejection_reason.lower()

    def test_check_order_warning_when_tilt_caution(self):
        from risk.safety_layer import OrderRequest, SafetyLayer

        class FakeConfig:
            LIVE_TRADING_ENABLED = True
            REQUIRE_HUMAN_APPROVAL = False
            MAX_DAILY_LOSS_PCT = 0.02
            MAX_DRAWDOWN_PCT = 0.10
            MAX_SINGLE_ORDER_VALUE = 50000.0
            MAX_POSITION_SIZE_PCT = 0.25
            MAX_ORDERS_PER_MINUTE = 10
            MAX_CONTRACTS_PER_INSTRUMENT = 5
            MAX_OVERNIGHT_CONTRACTS = 5

        sl = SafetyLayer(FakeConfig())
        td = TiltDetector()
        _record_losses(td, 3)  # score=0.2 → caution → 0.75x
        td.record_risk_veto()
        td.record_risk_veto()  # +0.2 → 0.4 → caution
        sl.tilt_detector = td

        order = OrderRequest(
            symbol="MES",
            quantity=4,
            order_type="market",
            is_futures=True,
            estimated_value=20000.0,
        )
        result = sl.check_order(order, portfolio_equity=100000.0)
        assert result.approved
        assert any("tilt" in w.lower() for w in result.warnings)
