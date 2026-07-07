"""
JARVIS TRADER — LLM-Driven Strategy Discovery Loop
Autonomous strategy generation, evaluation, and evolution.
Inspired by rv64m/autotrade's forever-loop pattern.

The loop:
1. LLM generates a new strategy file
2. Sandbox validates and loads it
3. Backtester runs the strategy
4. Evaluation harness produces verdict (ELIGIBLE/DISCARD/CRASH)
5. Results logged to JSONL with structured thoughts
6. ELIGIBLE strategies get keep=True, DISCARD moved to .trash/

Safety: All generated code runs through llm_sandbox validation.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

GENERATED_DIR = Path(__file__).parent / "generated"
TRASH_DIR = Path(__file__).parent / ".trash"
RESULTS_FILE = Path(__file__).parent / "results.jsonl"

# Ensure directories exist
GENERATED_DIR.mkdir(exist_ok=True)
TRASH_DIR.mkdir(exist_ok=True)


def log_result(record: dict) -> None:
    """Append a result record to the JSONL log."""
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def read_results(limit: int = 50) -> list[dict]:
    """Read recent results from the JSONL log."""
    if not RESULTS_FILE.exists():
        return []
    results = []
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return results[-limit:]


def get_top_strategies(n: int = 3) -> list[dict]:
    """Return top N strategies by Sharpe ratio from results log."""
    results = read_results(200)
    eligible = [r for r in results if r.get("verdict") == "ELIGIBLE"]
    eligible.sort(key=lambda r: r.get("sharpe", 0), reverse=True)
    return eligible[:n]


def discard_strategy(filename: str) -> None:
    """Move a strategy file to .trash/."""
    src = GENERATED_DIR / filename
    if src.exists():
        dst = TRASH_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        shutil.move(str(src), str(dst))
        logger.info(f"Discarded strategy: {filename} -> {dst.name}")


def evaluate_strategy_file(
    filename: str,
    symbol: str = "MCL",
    start: str = "2024-06-01",
    end: str = "2026-03-01",
    interval: str = "1h",
) -> dict:
    """
    Run a single strategy through the full evaluation pipeline.

    1. Load via sandbox
    2. Load market data
    3. Generate signals
    4. Run backtest
    5. Evaluate with harness
    6. Return result dict

    Returns dict with verdict, metrics, and thoughts.
    """
    from backtest.evaluation_harness import Verdict, evaluate
    from strategies.llm_sandbox import SandboxError, load_strategy_sandboxed

    result_record = {
        "strategy_file": filename,
        "symbol": symbol,
        "interval": interval,
        "timestamp": datetime.now().isoformat(),
    }

    # Step 1: Load strategy
    path = GENERATED_DIR / filename
    try:
        strategy_cls = load_strategy_sandboxed(path)
        strategy = strategy_cls(symbol=symbol)
    except SandboxError as e:
        result_record.update(
            {
                "verdict": Verdict.CRASH.value,
                "thoughts": f"Sandbox validation failed: {e}",
                "sharpe": 0.0,
                "calmar": 0.0,
                "pf": 0.0,
                "num_trades": 0,
            }
        )
        log_result(result_record)
        discard_strategy(filename)
        return result_record

    # Step 2: Load market data
    try:
        from backtest.data_loader import BacktestDataLoader

        loader = BacktestDataLoader()
        df = loader.load(symbol, start, end, interval)
        if df is None or df.empty:
            raise ValueError(f"No data for {symbol}")
    except Exception as e:
        result_record.update(
            {
                "verdict": Verdict.CRASH.value,
                "thoughts": f"Data load failed: {e}",
                "sharpe": 0.0,
                "calmar": 0.0,
                "pf": 0.0,
                "num_trades": 0,
            }
        )
        log_result(result_record)
        return result_record

    # Step 3: Generate signals
    try:
        signals_df = strategy.generate_signals(df)
    except Exception as e:
        result_record.update(
            {
                "verdict": Verdict.CRASH.value,
                "thoughts": f"Signal generation crashed: {e}",
                "sharpe": 0.0,
                "calmar": 0.0,
                "pf": 0.0,
                "num_trades": 0,
            }
        )
        log_result(result_record)
        discard_strategy(filename)
        return result_record

    # Step 4: Run backtest (using strategy's signal column)
    try:
        from backtest.backtester import Backtester
        from backtest.data_loader import CONTRACT_MULTIPLIERS

        multiplier = CONTRACT_MULTIPLIERS.get(symbol, 1.0)
        backtester = Backtester(
            initial_capital=10000,
            risk_per_trade=0.01,
            multiplier=multiplier,
        )
        bt_result = backtester.run(signals_df, symbol=symbol)
        bt_result.total_bars = len(signals_df)
    except Exception as e:
        result_record.update(
            {
                "verdict": Verdict.CRASH.value,
                "thoughts": f"Backtest crashed: {e}",
                "sharpe": 0.0,
                "calmar": 0.0,
                "pf": 0.0,
                "num_trades": 0,
            }
        )
        log_result(result_record)
        discard_strategy(filename)
        return result_record

    # Step 5: Evaluate with harness
    eval_result = evaluate(bt_result)

    result_record.update(
        {
            "verdict": eval_result.verdict.value,
            "layer1_passed": eval_result.layer1_passed,
            "layer2_passed": eval_result.layer2_passed,
            "violations": eval_result.violations,
            "sharpe": bt_result.sharpe_ratio,
            "calmar": bt_result.calmar_ratio,
            "pf": bt_result.profit_factor,
            "num_trades": bt_result.total_trades,
            "win_rate": bt_result.win_rate,
            "max_drawdown_pct": bt_result.max_drawdown_pct,
            "exposure_pct": bt_result.exposure_time_pct,
            "total_pnl": bt_result.total_pnl,
            "thoughts": (
                f"Strategy {strategy.name}: {eval_result.summary()}. "
                f"Trades={bt_result.total_trades}, PF={bt_result.profit_factor:.2f}, "
                f"Sharpe={bt_result.sharpe_ratio:.2f}, DD={bt_result.max_drawdown_pct:.2%}"
            ),
            "description": strategy.description,
        }
    )

    # Step 6: Classify
    if eval_result.verdict == Verdict.ELIGIBLE:
        # Mark as keeper in the strategy file
        logger.info(f"ELIGIBLE strategy found: {filename}")
    elif eval_result.verdict in (Verdict.DISCARD_RISK, Verdict.DISCARD_PROFIT):
        discard_strategy(filename)
    elif eval_result.verdict == Verdict.CRASH:
        discard_strategy(filename)

    log_result(result_record)
    return result_record


async def generate_strategy(
    symbol: str,
    interval: str = "1h",
    top_n_results: list[dict] | None = None,
) -> str | None:
    """
    Use Claude to generate a novel trading strategy Python file.
    Returns path to the written file, or None on failure.

    Routes through JarvisLLMClient so Anthropic credit-exhaustion silently
    falls over to Gemini (when GOOGLE_API_KEY is set) and the call is tracked
    in the cost DB. Anthropic library availability is checked inside the
    client, not here.
    """
    # Build top strategies summary for the prompt
    top_strategies = top_n_results or get_top_strategies(3)
    if top_strategies:
        summary_lines = []
        for i, s in enumerate(top_strategies, 1):
            summary_lines.append(
                f"  {i}. {s.get('strategy_file', 'unknown')} — "
                f"Sharpe={s.get('sharpe', 0):.2f}, PF={s.get('pf', 0):.2f}, "
                f"WR={s.get('win_rate', 0):.1%}, Trades={s.get('num_trades', 0)}"
            )
        top_strategies_summary = "\n".join(summary_lines)
    else:
        top_strategies_summary = "  (no prior results — this is the first generation)"

    system_prompt = (
        "You are an expert quantitative trading strategy developer working within the JARVIS TRADER system.\n\n"
        "CONTEXT:\n"
        "- Base class: `from strategies.base_strategy import BaseStrategy`\n"
        "- Available indicators (from `backtest.indicators`): STC, ATR, EMA, RSI, MACD, Bollinger Bands\n"
        "- Required interface: implement `generate_signals(df: pd.DataFrame) -> pd.DataFrame`\n"
        "  - Input df has columns: open, high, low, close, volume (lowercase)\n"
        "  - Output must add columns: signal (1=long, -1=short, 0=no signal), "
        "stop_price (float), target_price (float)\n"
        "- Your class MUST subclass BaseStrategy and set self.name and self.description in __init__\n"
        "- Use only standard libraries + pandas + numpy + the indicators listed above\n"
        "- No external API calls, no file I/O, no side effects\n"
        "- Code must be self-contained, syntactically valid Python 3.12+\n\n"
        "RULES:\n"
        "- Return ONLY valid Python code — no markdown fences, no explanation, no comments outside code\n"
        "- The class must be importable as a standalone module\n"
        "- Handle edge cases (insufficient data, NaN values) gracefully\n"
    )

    user_prompt = (
        f"Generate a novel trading strategy for {symbol} on {interval} bars.\n\n"
        f"Current top strategies by Sharpe:\n{top_strategies_summary}\n\n"
        "Do NOT replicate these approaches. Use a fundamentally different entry/exit logic.\n"
        "Consider: mean reversion, breakout, volatility contraction, regime-switching, "
        "multi-timeframe confirmation, or cross-asset signals.\n"
        "Return ONLY valid Python code, no markdown, no explanation."
    )

    # Determine next sequential file number
    existing = sorted(GENERATED_DIR.glob("llm_strategy_*.py"))
    next_n = len(existing) + 1
    out_path = GENERATED_DIR / f"llm_strategy_{next_n}.py"

    try:
        from llm.client import JarvisLLMClient

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        db_path = os.getenv("JARVIS_LLM_COST_DB", "data/llm_costs.db")
        llm = JarvisLLMClient(api_key=api_key, db_path=db_path)
        result = await llm.call(
            model="claude-sonnet-4-6",
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=4000,
            agent_name="discovery_loop",
        )
        if not result.success:
            raise RuntimeError(result.error or "LLM call failed without error message")
        code = result.content
    except Exception as e:
        logger.error(f"LLM strategy generation API call failed: {e}")
        return None

    # Strip markdown fences if the model added them anyway
    if code.startswith("```"):
        lines = code.splitlines()
        # Drop first line (```python or ```) and last ``` fence
        start = 1 if lines[0].startswith("```") else 0
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        code = "\n".join(lines[start:end])

    # Validate: try llm_sandbox first, fall back to compile()
    try:
        from strategies.llm_sandbox import validate_strategy_source

        violations = validate_strategy_source(code)
        if violations:
            logger.warning(
                f"LLM strategy failed sandbox validation ({len(violations)} violations): "
                + "; ".join(violations[:3])
            )
            return None
    except ImportError:
        try:
            compile(code, "<generated>", "exec")
        except SyntaxError as e:
            logger.warning(f"LLM strategy has syntax error: {e}")
            return None

    # Write to disk
    try:
        out_path.write_text(code, encoding="utf-8")
        logger.info(f"LLM strategy written: {out_path.name}")
        return str(out_path)
    except OSError as e:
        logger.error(f"Failed to write strategy file {out_path}: {e}")
        return None


def get_discovery_status() -> dict:
    """Return current discovery status for the API."""
    results = read_results(200)
    return {
        "total_experiments": len(results),
        "eligible": sum(1 for r in results if r.get("verdict") == "ELIGIBLE"),
        "discarded_risk": sum(1 for r in results if r.get("verdict") == "DISCARD_RISK"),
        "discarded_profit": sum(1 for r in results if r.get("verdict") == "DISCARD_PROFIT"),
        "crashed": sum(1 for r in results if r.get("verdict") == "CRASH"),
        "top_strategies": get_top_strategies(3),
        "generated_count": len(list(GENERATED_DIR.glob("*.py"))) - 1,  # exclude __init__
        "trash_count": len(list(TRASH_DIR.glob("*.py"))),
    }
