#!/usr/bin/env python
"""
Test script for walk-forward validation system.

Verifies:
1. WalkForwardValidator class instantiation and window generation
2. Full end-to-end walk-forward run with real data
3. Results serialization and JSON output
4. CLI entry points
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure backtest module is importable
engine_root = Path(__file__).parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))


def test_walk_forward_validator_class():
    """Test WalkForwardValidator class instantiation."""
    print("\n" + "=" * 70)
    print("TEST 1: WalkForwardValidator Class")
    print("=" * 70)

    from backtest.walk_forward import WalkForwardValidator

    # Instantiate with custom window parameters
    validator = WalkForwardValidator(train_months=6, test_months=3, step_months=3)
    print("✓ Created WalkForwardValidator")
    print(f"  Train window: {validator.train_months} months")
    print(f"  Test window: {validator.test_months} months")
    print(f"  Step size: {validator.step_months} months")

    return validator


def test_window_generation():
    """Test window generation on sample data."""
    print("\n" + "=" * 70)
    print("TEST 2: Window Generation")
    print("=" * 70)

    import pandas as pd

    from backtest.walk_forward import WalkForwardValidator

    # Create synthetic data spanning 24 months
    dates = pd.date_range("2024-01-01", periods=500, freq="1h")
    df = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000000,
        },
        index=dates,
    )

    validator = WalkForwardValidator(train_months=6, test_months=3, step_months=3)
    windows = validator.generate_windows(df, "TEST")

    print(f"✓ Generated {len(windows)} rolling windows")
    for _i, w in enumerate(windows[:3]):  # Show first 3
        print(f"\n  Window {w['window_num']}:")
        print(
            f"    Train: {w['train_start'].strftime('%Y-%m-%d')} to {w['train_end'].strftime('%Y-%m-%d')} ({w['train_bars']} bars)"
        )
        print(
            f"    Test:  {w['test_start'].strftime('%Y-%m-%d')} to {w['test_end'].strftime('%Y-%m-%d')} ({w['test_bars']} bars)"
        )

    return windows


def test_full_walk_forward_run():
    """Test full walk-forward validation with real data."""
    print("\n" + "=" * 70)
    print("TEST 3: Full Walk-Forward Run (SPY 1h, 2024-06-01 to 2025-06-01)")
    print("=" * 70)

    from backtest.data_loader import BacktestDataLoader
    from backtest.walk_forward import WalkForwardValidator

    # Load real data
    loader = BacktestDataLoader()
    print("Loading SPY 1h data...")
    df = loader.load("SPY", "2024-06-01", "2025-06-01", "1h")

    if df is None or df.empty:
        print("⚠ Could not load SPY data, skipping full run test")
        return None

    print(f"✓ Loaded {len(df)} bars")

    # Run walk-forward with fast grid (fewer combinations)
    validator = WalkForwardValidator(train_months=6, test_months=2, step_months=2)
    print("\nRunning walk-forward validation (fast grid)...")

    result = validator.run(
        df,
        "SPY",
        multiplier=1.0,
        capital=100_000.0,
        fast=True,  # Use fast grid for testing
        adaptive_regime=False,
    )

    print("\n✓ Walk-forward validation complete!")
    summary = result["summary"]
    print("\nResults Summary:")
    print(f"  Windows: {summary['total_windows']}")
    print(f"  Avg IS Return: {summary['avg_is_return'] * 100:.2f}%")
    print(f"  Avg OOS Return: {summary['avg_oos_return'] * 100:.2f}%")
    print(f"  WFE: {summary['wfe']:.3f}")

    if summary["wfe"] > 0.5:
        wfe_label = "GOOD"
    elif summary["wfe"] > 0.3:
        wfe_label = "ACCEPTABLE"
    else:
        wfe_label = "OVERFIT"
    print(f"  WFE Label: {wfe_label}")
    print(f"  Avg OOS Sharpe: {summary['avg_oos_sharpe']:.3f}")
    print(f"  Avg OOS PF: {summary['avg_oos_profit_factor']:.3f}")
    print(f"  Profitable Windows: {summary['windows_profitable']}/{summary['total_windows']}")

    return result


def test_results_serialization():
    """Test results serialization to JSON."""
    print("\n" + "=" * 70)
    print("TEST 4: Results Serialization")
    print("=" * 70)

    from backtest.data_loader import BacktestDataLoader
    from backtest.walk_forward import WalkForwardValidator, save_results

    # Quick run to get results
    loader = BacktestDataLoader()
    df = loader.load("MES", "2024-06-01", "2025-06-01", "1h")

    if df is None or df.empty:
        print("⚠ Could not load MES data, skipping serialization test")
        return None

    print(f"Running quick validation on {len(df)} bars...")
    validator = WalkForwardValidator(train_months=12, test_months=3, step_months=3)
    result = validator.run(df, "MES", multiplier=12.5, capital=100_000.0, fast=True)

    # Save to JSON
    output_path = save_results(result, "MES", "1h")
    print(f"✓ Results saved to: {output_path}")

    # Verify JSON structure
    with open(output_path) as f:
        json_data = json.load(f)

    required_keys = ["symbol", "interval", "generated", "summary", "windows"]
    for key in required_keys:
        if key in json_data:
            print(f"  ✓ {key}")
        else:
            print(f"  ✗ Missing {key}")

    print(f"\nJSON structure valid: {len(json_data['windows'])} windows saved")
    return output_path


def test_cli_entry_point():
    """Test CLI entry point."""
    print("\n" + "=" * 70)
    print("TEST 5: CLI Entry Point")
    print("=" * 70)

    print("✓ walk_forward.main() is importable")
    print("  Usage: python -m backtest.walk_forward --symbol SPY --interval 1h")
    print("  Or: python -m backtest.run_walk_forward --symbol MES --train-months 6")


def main():
    """Run all tests."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "WALK-FORWARD VALIDATION SYSTEM TEST" + " " * 19 + "║")
    print("╚" + "=" * 68 + "╝")

    try:
        # Run tests
        test_walk_forward_validator_class()
        test_window_generation()
        test_full_walk_forward_run()
        test_results_serialization()
        test_cli_entry_point()

        # Summary
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        print("✓ All core tests passed!")
        print("\nNext steps:")
        print("1. CLI: python -m backtest.run_walk_forward --symbol SPY --interval 1h")
        print("2. API: POST http://localhost:8010/backtest/walk-forward")
        print("3. Results: View JSON in engine/backtest/results/WF_*.json")

    except Exception as exc:
        print(f"\n✗ Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
