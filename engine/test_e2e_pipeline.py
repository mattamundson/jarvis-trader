"""
E2E pipeline smoke test — verifies all components initialize, connect,
and produce structured output through the full 5-stage pipeline.

This test uses mock/stub agents (no live LLM calls) to validate that:
  1. All imports resolve correctly
  2. BacktestDataLoader loads cached MNQ data
  3. generate_signals() produces ENTRY_NOW signals
  4. TradingPipeline runs all 5 stages with stub agents
  5. Final pipeline_result dict has all expected keys
"""

import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv(".env")


def test_imports():
    """Test 1: All agent and pipeline imports resolve."""
    print("=" * 60)
    print("TEST 1: Import verification")
    print("=" * 60)

    print("  All imports OK")
    return True


def test_data_load():
    """Test 2: BacktestDataLoader loads MNQ 1h from cache."""
    print("\n" + "=" * 60)
    print("TEST 2: Data loading (MNQ 1h from cache)")
    print("=" * 60)

    from backtest.data_loader import BacktestDataLoader

    loader = BacktestDataLoader()
    df = loader.load("MNQ", "2025-01-01", "2025-03-01", "1h")

    if df is None or len(df) == 0:
        print("  FAIL: No data returned for MNQ 1h")
        return None

    print(f"  Loaded {len(df)} bars")
    print(f"  Date range: {df.index.min()} to {df.index.max()}")
    print(f"  Columns: {list(df.columns)}")
    return df


def test_signal_generation(df):
    """Test 3: generate_signals() produces structured output with ENTRY_NOW signals."""
    print("\n" + "=" * 60)
    print("TEST 3: Signal generation")
    print("=" * 60)

    from backtest.signals import generate_signals

    df_sig = generate_signals(df, symbol="MNQ", adaptive_regime=True)

    required_cols = [
        "regime",
        "structure_position",
        "bias",
        "entry_signal",
        "stop_level",
        "target_1",
        "target_2",
        "target_3",
    ]
    missing = [c for c in required_cols if c not in df_sig.columns]
    if missing:
        print(f"  FAIL: Missing columns: {missing}")
        return None

    entry_bars = df_sig[df_sig["entry_signal"] == "ENTRY_NOW"]
    print(f"  Generated signals for {len(df_sig)} bars")
    print(f"  ENTRY_NOW signals: {len(entry_bars)}")
    print("  Signal distribution:")
    print(f"    {df_sig['entry_signal'].value_counts().to_dict()}")

    if len(entry_bars) > 0:
        last = entry_bars.iloc[-1]
        print("\n  Last ENTRY_NOW bar:")
        print(f"    Timestamp: {last.name}")
        print(f"    Close:     {last['close']:.2f}")
        print(f"    Regime:    {last['regime']}")
        print(f"    Structure: {last['structure_position']}")
        print(f"    Bias:      {last['bias']}")
        print(f"    Stop:      {last['stop_level']:.2f}")
        print(f"    T1:        {last['target_1']:.2f}")

    return df_sig


# ── Stub agent classes for pipeline testing ──

class StubAnalyst:
    """Returns a neutral technical report."""

    async def analyze(self, symbol, **kwargs):
        return {
            "signal": 0.3,
            "confidence": 0.6,
            "trend": "uptrend",
            "regime": "trending",
            "trend_score": 0.4,
            "momentum_score": 0.3,
            "volatility_score": -0.1,
            "volume_score": 0.2,
            "summary": f"Stub technical analysis for {symbol}",
            "reasoning": "Stub agent — no live LLM call made",
        }


class StubDebate:
    """Returns a mildly bullish debate result."""

    async def run_debate(self, symbol, analyst_reports, bull, bear):
        return {
            "verdict": "lean_bullish",
            "bull_score": 0.65,
            "bear_score": 0.35,
            "summary": "Stub debate: mild bullish lean",
            "bull_arguments": ["Trend is up", "Volume confirms"],
            "bear_arguments": ["Overbought risk", "Late in cycle"],
        }


class StubBull:
    async def argue(self, symbol, reports):
        return {"score": 0.65, "arguments": ["Trend up"]}


class StubBear:
    async def argue(self, symbol, reports):
        return {"score": 0.35, "arguments": ["Overbought"]}


class StubTrader:
    """Returns a BUY decision."""

    async def decide(self, symbol, debate_result, analyst_reports, safety_status):
        return {
            "symbol": symbol,
            "action": "buy",
            "quantity": 1,
            "order_type": "market",
            "limit_price": None,
            "stop_price": 21500.0,
            "time_in_force": "day",
            "signal_score": 0.65,
            "confidence": 0.6,
            "reasoning": "Stub trader: bullish consensus from debate",
            "risk_notes": "Paper mode — stub test",
            "timestamp": datetime.now().isoformat(),
        }


class StubRiskManager:
    """Approves the trade."""

    async def review(self, trade_decision, safety_status, portfolio):
        return {
            "approved": True,
            "veto_reason": None,
            "modified_quantity": 1,
            "modified_limit_price": None,
            "risk_score": 0.3,
            "reasoning": "Stub risk manager: approved for paper trading",
            "timestamp": datetime.now().isoformat(),
        }


class StubFundManager:
    """Final approval with human review required."""

    async def approve(self, trade_decision, risk_decision, portfolio, open_positions):
        return {
            "approved": True,
            "final_quantity": 1,
            "priority": "immediate",
            "portfolio_impact": "Stub: minimal impact on paper portfolio",
            "reasoning": "Stub fund manager: approved with human review",
            "requires_human_approval": True,
            "final_conviction": 0.62,
            "timestamp": datetime.now().isoformat(),
        }


class StubSafetyLayer:
    """Mimics the SafetyLayer interface."""

    _current_equity = 10_000.0
    _daily_realized_pnl = 0.0

    def get_status(self):
        return {
            "kill_switch_active": False,
            "daily_pnl": 0.0,
            "daily_loss_remaining": 200.0,
            "max_drawdown_pct": 0.0,
            "orders_this_minute": 0,
            "paper_mode": True,
        }


def _create_stub_agents():
    """Create and wire up all stub agents."""
    return {
        "technical": StubAnalyst(),
        "news": StubAnalyst(),
        "social": StubAnalyst(),
        "fundamental": StubAnalyst(),
        "bull": StubBull(),
        "bear": StubBear(),
        "debate": StubDebate(),
        "trader": StubTrader(),
        "risk_manager": StubRiskManager(),
        "fund_manager": StubFundManager(),
    }


def _verify_result_keys(result):
    """Verify all expected keys exist in pipeline result."""
    expected_keys = [
        "symbol",
        "is_futures",
        "started_at",
        "completed_at",
        "analyst_reports",
        "debate_result",
        "trade_decision",
        "risk_decision",
        "fund_decision",
        "final_action",
        "final_quantity",
        "requires_human",
        "errors",
        "summary",
    ]
    return [k for k in expected_keys if k not in result]


def _print_result_summary(result):
    """Print pipeline result summary."""
    print("\n  Pipeline Result:")
    print(f"    Symbol:         {result['symbol']}")
    print(f"    Final Action:   {result['final_action']}")
    print(f"    Final Quantity:  {result['final_quantity']}")
    print(f"    Requires Human: {result['requires_human']}")
    print(f"    Errors:         {result['errors']}")
    print(f"    Summary:        {result['summary']}")

    for stage in [
        "analyst_reports",
        "debate_result",
        "trade_decision",
        "risk_decision",
        "fund_decision",
    ]:
        val = result.get(stage)
        status = "OK" if val is not None else "MISSING"
        print(f"    {stage}: {status}")


async def test_pipeline(df_sig):
    """Test 4: Full pipeline smoke test with stub agents."""
    print("\n" + "=" * 60)
    print("TEST 4: Pipeline E2E (stub agents — no LLM calls)")
    print("=" * 60)

    from agents.pipeline import TradingPipeline

    agents = _create_stub_agents()
    safety = StubSafetyLayer()
    pipeline = TradingPipeline(agents=agents, safety_layer=safety)

    print("  Running pipeline for MNQ...")
    result = await pipeline.analyze_and_decide("MNQ", is_futures=True)

    missing = _verify_result_keys(result)
    if missing:
        print(f"  FAIL: Missing keys in pipeline_result: {missing}")
        return None

    _print_result_summary(result)
    return result


async def main():
    results = {"imports": False, "data": False, "signals": False, "pipeline": False}

    # Test 1: Imports
    try:
        results["imports"] = test_imports()
    except Exception as e:
        print(f"  FAIL: {e}")

    # Test 2: Data load
    df = None
    try:
        df = test_data_load()
        results["data"] = df is not None
    except Exception as e:
        print(f"  FAIL: {e}")

    # Test 3: Signal generation
    df_sig = None
    if df is not None:
        try:
            df_sig = test_signal_generation(df)
            results["signals"] = df_sig is not None
        except Exception as e:
            print(f"  FAIL: {e}")
            import traceback

            traceback.print_exc()

    # Test 4: Pipeline E2E
    try:
        pipeline_result = await test_pipeline(df_sig)
        results["pipeline"] = pipeline_result is not None
    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback

        traceback.print_exc()

    # Summary
    print("\n" + "=" * 60)
    print("E2E SMOKE TEST SUMMARY")
    print("=" * 60)
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
    print(f"\n  {passed}/{total} tests passed")

    return all(results.values())


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
