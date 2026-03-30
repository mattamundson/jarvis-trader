#!/usr/bin/env python3
"""
Simple validation script for ConsecutiveLossTracker
(without external dependencies)
"""
import sys
import tempfile
from pathlib import Path

# Add engine to path
sys.path.insert(0, str(Path(__file__).parent))

from risk.loss_tracker import ConsecutiveLossTracker


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


def test_multiplier_thresholds():
    """Test position size multiplier at all thresholds"""
    print("\n=== Test 2: Multiplier Thresholds ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = ConsecutiveLossTracker(
            data_dir=tmpdir,
            consecutive_loss_half_size=3,
            consecutive_loss_quarter_size=5,
            consecutive_loss_halt=7,
        )

        # 0-2 losses: 1.0x
        for i in range(1, 3):
            tracker.record_trade("MES", -50.0)
            assert tracker.get_position_size_multiplier() == 1.0, f"At {i} losses, should be 1.0x"
        print("✅ 0-2 losses: 1.0x ✓")

        # 3 losses: 0.5x
        tracker.record_trade("MES", -50.0)
        assert tracker.get_position_size_multiplier() == 0.5, "At 3 losses, should be 0.5x"
        print("✅ 3 losses: 0.5x ✓")

        # 4-5 losses: 0.5x (but 5 triggers quarter)
        tracker.record_trade("MES", -50.0)
        assert tracker.get_position_size_multiplier() == 0.5, "At 4 losses, should be 0.5x"
        print("✅ 4 losses: 0.5x ✓")

        # 5 losses: 0.25x
        tracker.record_trade("MES", -50.0)
        assert tracker.get_position_size_multiplier() == 0.25, "At 5 losses, should be 0.25x"
        print("✅ 5 losses: 0.25x ✓")

        # 6 losses: 0.25x
        tracker.record_trade("MES", -50.0)
        assert tracker.get_position_size_multiplier() == 0.25, "At 6 losses, should be 0.25x"
        print("✅ 6 losses: 0.25x ✓")

        # 7 losses: 0.0x (halt)
        tracker.record_trade("MES", -50.0)
        assert tracker.is_halted(), "At 7 losses, should be halted"
        assert tracker.get_position_size_multiplier() == 0.0, "At 7 losses, should be 0.0x"
        print("✅ 7 losses: 0.0x (HALTED) ✓")


def test_halt_logic():
    """Test trading halt at 7 losses"""
    print("\n=== Test 3: Trading Halt Logic ===")

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
    print("\n=== Test 4: Symbol-Specific Tracking ===")

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

        # A win on MES resets global (not symbol-specific)
        tracker.record_trade("MES", 100.0)
        assert tracker.get_consecutive_losses() == 0, "Win should reset global"
        assert tracker.get_consecutive_losses("MES") == 0, "Symbol should also be reset"
        print("✅ Win on one symbol resets global counter")


def test_persistence():
    """Test state persistence across restarts"""
    print("\n=== Test 5: State Persistence ===")

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


def test_manual_reset():
    """Test manual reset functionality"""
    print("\n=== Test 6: Manual Reset ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)

        # Record losses
        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MNQ", -50.0)

        assert tracker.get_consecutive_losses() == 3, "Should have 3 losses"

        # Reset global
        tracker.reset()
        assert tracker.get_consecutive_losses() == 0, "Global should be reset"
        assert tracker.get_consecutive_losses("MES") == 0, "All symbols should be reset"
        print("✅ Global reset works")

        # Record again
        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MNQ", -50.0)

        # Reset specific symbol
        tracker.reset(symbol="MES")
        assert tracker.get_consecutive_losses("MES") == 0, "MES should be reset"
        assert tracker.get_consecutive_losses("MNQ") == 1, "MNQ should remain"
        print("✅ Symbol-specific reset works")


def test_status_report():
    """Test comprehensive status reporting"""
    print("\n=== Test 7: Status Report ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)
        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MNQ", -50.0)

        status = tracker.get_status()

        # Check all required fields
        assert "global_consecutive_losses" in status
        assert "symbol_losses" in status
        assert "position_size_multiplier" in status
        assert "is_halted" in status
        assert "halt_until" in status
        assert "last_trade_symbol" in status
        assert "last_trade_timestamp" in status
        assert "config" in status

        assert status["global_consecutive_losses"] == 3
        assert status["symbol_losses"]["MES"] == 2
        assert status["symbol_losses"]["MNQ"] == 1
        assert status["position_size_multiplier"] == 0.5, f"With 3 losses should be 0.5x, got {status['position_size_multiplier']}"
        assert status["is_halted"] is False
        assert status["last_trade_symbol"] == "MNQ"

        print("✅ Status report contains all required fields and correct values")


def main():
    """Run all tests"""
    print("=" * 70)
    print("CONSECUTIVE LOSS TRACKER VALIDATION")
    print("=" * 70)

    tests = [
        ("Basic Functionality", test_basic_functionality),
        ("Multiplier Thresholds", test_multiplier_thresholds),
        ("Trading Halt Logic", test_halt_logic),
        ("Symbol-Specific Tracking", test_symbol_tracking),
        ("State Persistence", test_persistence),
        ("Manual Reset", test_manual_reset),
        ("Status Report", test_status_report),
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

    if failed == 0:
        print("\n🎉 All tests passed!")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
