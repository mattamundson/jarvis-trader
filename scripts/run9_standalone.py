#!/usr/bin/env python
"""
Run 9 — MES Two-Lever Training (Standalone)
==============================================
Runs outside FastAPI/PM2. Training persists regardless of engine restarts.

Usage:
    cd engine
    .venv/Scripts/python ../scripts/run9_standalone.py

Output: prints progress, saves model to data/rl_models/
"""
import asyncio
import sys
import time
from pathlib import Path

# Add engine dir to path
ENGINE_DIR = Path(__file__).parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from strategies.rl_trainer import RLTrainer


async def main():
    symbol = "MES"
    timesteps = 500_000

    print(f"\n{'='*60}")
    print(f"JARVIS TRADER — RL Run 9 (Two-Lever Config)")
    print(f"Symbol: {symbol} | Timesteps: {timesteps:,}")
    print(f"entry_cost=-0.02 | hold_cost=-0.002 | break-even=10 bars")
    print(f"{'='*60}\n")

    trainer = RLTrainer(data_manager=None)

    t0 = time.time()
    result = await trainer.train_symbol(
        symbol=symbol,
        interval="1h",
        timesteps=timesteps,
    )
    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(f"Training complete in {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"Status: {result.get('status')}")
    print(f"Model:  {result.get('model_path')}")
    metrics = result.get("metrics", {})
    print(f"\nMetrics:")
    print(f"  n_trades:         {metrics.get('n_trades')}")
    print(f"  win_rate:         {metrics.get('win_rate', 0):.1%}")
    print(f"  profit_factor:    {metrics.get('profit_factor', 0):.3f}")
    print(f"  sharpe:           {metrics.get('sharpe', 0):.3f}")
    print(f"  max_drawdown:     {metrics.get('max_drawdown', 0):.1%}")
    print(f"  hold_rate:        {metrics.get('hold_rate', 0):.1%}")
    print(f"  t1_hit_rate:      {metrics.get('t1_hit_rate', 0):.1%}")
    print(f"  avg_bars_in_trade:{metrics.get('avg_bars_in_trade', 0):.1f}")
    ts = result.get("training_summary", {})
    print(f"\nAction distribution:")
    for action, pct in ts.get("action_distribution", {}).items():
        bar = "█" * int(pct * 30)
        print(f"  {action:5s}: {pct:.1%}  {bar}")
    print(f"\nValidation: {'PASS ✅' if metrics.get('passes_validation') else 'FAIL ❌'}")
    gates = {
        "n_trades >= 30":       metrics.get('n_trades', 0) >= 30,
        "hold_rate < 0.60":     metrics.get('hold_rate', 0) < 0.60,
        "profit_factor > 1.5":  metrics.get('profit_factor', 0) > 1.5,
        "sharpe > 1.0":         metrics.get('sharpe', 0) > 1.0,
        "max_drawdown < 0.10":  metrics.get('max_drawdown', 0) < 0.10,
    }
    for gate, passed in gates.items():
        print(f"  {'✅' if passed else '❌'} {gate}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
