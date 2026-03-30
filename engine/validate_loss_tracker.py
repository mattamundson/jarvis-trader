#!/usr/bin/env python3
"""
Simple validation script for ConsecutiveLossTracker integration
(without requiring pytest)
"""

import sys
import tempfile
from pathlib import Path

# Add engine to path
sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from risk.loss_tracker import ConsecutiveLossTracker
from risk.safety_layer import OrderRequest, SafetyLayer


def test_basic_functionality():
    """Test basic loss tracker functionality"""
    print("\n=== Test 1: Basic Functionality ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)

        # Initial state
        assert tracker.get_consecutive_losses() == 0, "Should start at 0 losses"
        assert tracker.get_position_size_multiplier() == 1.0, "Should start at 1.0x"
        print("✅ Initial state correct")

        # Record losses
        tracker.record_trade("MES", -100.0)
        assert tracker.get_consecutive_losses() == 1, "Should have 1 loss"
        print("✅ Single loss recorded")

        # Record more losses
        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MES", -100.0)
        assert tracker.get_consecutive_losses() == 3, "Should have 3 losses"
        assert tracker.get_position_size_multiplier() == 0.5, "Should be at 0.5x (3 losses)"
        print("✅ Position size reduction triggered at 3 losses")

        # Record win - should reset
        tracker.record_trade("MES", 150.0)
        assert tracker.get_consecutive_losses() == 0, "Win should reset counter"
        assert tracker.get_position_size_multiplier() == 1.0, "Should return to 1.0x"
        print("✅ Win resets counter correctly")


def test_halt_logic():
    """Test trading halt at 7 losses"""
    print("\n=== Test 2: Trading Halt Logic ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)

        # Record 7 losses
        for _i in range(7):
            tracker.record_trade("MES", -50.0)

        assert tracker.get_consecutive_losses() == 7, "Should have 7 losses"
        assert tracker.is_halted(), "Should be halted at 7 losses"
        assert tracker.get_position_size_multiplier() == 0.0, "Multiplier should be 0.0"
        print("✅ Trading halted at 7 losses")

        reason = tracker.get_halt_reason()
        assert "trading paused" in reason.lower(), "Should provide halt reason"
        print(f"✅ Halt reason: {reason}")


def test_symbol_tracking():
    """Test per-symbol loss tracking"""
    print("\n=== Test 3: Symbol-Specific Tracking ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)

        # Lose on MES
        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MES", -100.0)

        # Lose on MNQ
        tracker.record_trade("MNQ", -50.0)

        assert tracker.get_consecutive_losses("MES") == 2, "MES should have 2 losses"
        assert tracker.get_consecutive_losses("MNQ") == 1, "MNQ should have 1 loss"
        assert tracker.get_consecutive_losses() == 3, "Global should be 3"
        print("✅ Symbol-specific tracking works correctly")


def test_persistence():
    """Test state persistence across restarts"""
    print("\n=== Test 4: State Persistence ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create tracker and record trades
        t1 = ConsecutiveLossTracker(data_dir=tmpdir)
        t1.record_trade("MES", -100.0)
        t1.record_trade("MES", -100.0)
        t1.record_trade("MNQ", -50.0)

        # Create new instance from same directory
        t2 = ConsecutiveLossTracker(data_dir=tmpdir)
        assert t2.get_consecutive_losses() == 3, "Should load persisted state"
        assert t2.get_consecutive_losses("MES") == 2, "MES state should persist"
        assert t2.get_consecutive_losses("MNQ") == 1, "MNQ state should persist"
        print("✅ State correctly persisted and loaded")


def test_safety_layer_integration():
    """Test SafetyLayer integration"""
    print("\n=== Test 5: SafetyLayer Integration ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)
        layer = SafetyLayer(settings, loss_tracker=tracker)

        # Order with no losses should be approved
        order = OrderRequest(
            symbol="MES",
            quantity=2,
            order_type="market",
            estimated_value=500.0,
            is_futures=True,
        )
        result = layer.check_order(order, portfolio_equity=50000.0)
        assert result.approved, "Order should be approved with no losses"
        print("✅ Order approved with no losses")

        # Record losses
        for _i in range(3):
            tracker.record_trade("MES", -100.0)

        # Order should be approved but with warning
        result = layer.check_order(order, portfolio_equity=50000.0)
        assert result.approved, "Order should still be approved"
        assert len(result.warnings) > 0, "Should have warning about position size reduction"
        print(f"✅ Order approved with warning: {result.warnings[0][:60]}...")

        # Test recording trade via SafetyLayer API
        layer.record_trade_result("MES", -50.0)
        assert tracker.get_consecutive_losses() == 4, "Trade should be recorded"
        print("✅ Trade recording via SafetyLayer API works")

        # Test status API
        status = layer.get_loss_tracker_status()
        assert status["enabled"], "Loss tracker should be enabled"
        assert status["global_consecutive_losses"] == 4, "Should reflect correct loss count"
        print("✅ Status API returns correct information")

        # Test reset API
        layer.reset_loss_tracker()
        assert tracker.get_consecutive_losses() == 0, "Reset should clear counter"
        print("✅ Reset API works correctly")


def test_order_rejection_on_halt():
    """Test that orders are rejected when halted"""
    print("\n=== Test 6: Order Rejection on Halt ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)
        layer = SafetyLayer(settings, loss_tracker=tracker)

        # Trigger halt (7+ losses)
        for _i in range(7):
            tracker.record_trade("MES", -50.0)

        order = OrderRequest(
            symbol="MES",
            quantity=2,
            order_type="market",
            estimated_value=500.0,
            is_futures=True,
        )

        result = layer.check_order(order, portfolio_equity=50000.0)
        assert not result.approved, "Order should be rejected when halted"
        assert "halt" in result.rejection_reason.lower(), "Rejection reason should mention halt"
        assert "consecutive loss" in result.rejection_reason.lower(), "Should mention loss limit"
        print(f"✅ Order correctly rejected: {result.rejection_reason}")


def main():
    """Run all tests"""
    print("=" * 70)
    print("CONSECUTIVE LOSS TRACKER VALIDATION")
    print("=" * 70)

    tests = [
        ("Basic Functionality", test_basic_functionality),
        ("Halt Logic", test_halt_logic),
        ("Symbol Tracking", test_symbol_tracking),
        ("State Persistence", test_persistence),
        ("SafetyLayer Integration", test_safety_layer_integration),
        ("Order Rejection on Halt", test_order_rejection_on_halt),
    ]

    passed = 0
    failed = 0

    for _name, test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"\n❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
