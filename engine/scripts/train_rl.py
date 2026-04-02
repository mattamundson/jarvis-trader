#!/usr/bin/env python3
"""
JARVIS TRADER — Standalone RL Training CLI
==========================================
Trains a PPO reinforcement learning agent for a given futures symbol
and reports validation gate results.

Usage:
    cd engine
    python -m scripts.train_rl --symbol MES --bars 5000 --timesteps 100000
    python -m scripts.train_rl --symbol MES --dry-run
    python -m scripts.train_rl --symbol MES --timesteps 50000 --eval
    python -m scripts.train_rl --symbol MNQ --timesteps 500000  # production

Options:
    --symbol     Futures symbol (MES, MNQ, MCL, MGC). Default: MES
    --bars       Number of historical bars to use (approximate). Default: 5000
    --timesteps  PPO training timesteps. Default: 100000
    --eval       Run OOS evaluation after training (always true, kept for clarity)
    --dry-run    Validate imports and environment setup only — no training
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# ── Make sure we can import engine modules regardless of cwd ──────────────────
_ENGINE_DIR = Path(__file__).resolve().parent.parent  # engine/
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

# ── Logging: INFO to stdout, suppress noisy library loggers ──────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)
# Keep our own trainer logs visible at INFO
logging.getLogger("strategies").setLevel(logging.INFO)
logging.getLogger("scripts").setLevel(logging.INFO)
logger = logging.getLogger("scripts.train_rl")


# ── ANSI helpers ──────────────────────────────────────────────────────────────


def _supports_color() -> bool:
    """Return True if the terminal supports ANSI color codes."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_GREEN = "\033[92m" if _supports_color() else ""
_RED = "\033[91m" if _supports_color() else ""
_BOLD = "\033[1m" if _supports_color() else ""
_RESET = "\033[0m" if _supports_color() else ""


def _pass(value: str) -> str:
    return f"{_GREEN}{value} PASS{_RESET}"


def _fail(value: str) -> str:
    return f"{_RED}{value} FAIL{_RESET}"


# ── CLI argument parsing ──────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="train_rl",
        description="JARVIS RL Trainer — train and evaluate a PPO trading agent",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--symbol",
        default="MES",
        metavar="SYMBOL",
        help="Futures symbol to train on (MES, MNQ, MCL, MGC)",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=5000,
        metavar="N",
        help="Approximate number of historical bars to use (clipped to available data)",
    )
    parser.add_argument(
        "--timesteps",
        type=int,
        default=100_000,
        metavar="N",
        help="Total PPO training timesteps",
    )
    parser.add_argument(
        "--eval",
        action="store_true",
        default=True,
        help="Run OOS evaluation after training (default: enabled)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate imports and environment setup only — skip training",
    )
    return parser.parse_args(argv)


# ── Dry-run validation ────────────────────────────────────────────────────────


def run_dry_run(symbol: str, timesteps: int) -> int:
    """
    Validate that all required modules can be imported and the RL pipeline
    is wired correctly.  Does NOT fetch data or train.

    Returns 0 on success, 1 on failure.
    """
    print(f"\n{_BOLD}JARVIS RL Trainer — {symbol}{_RESET}")
    print("=" * 40)
    print("Mode: DRY-RUN (import + environment validation)\n")

    steps_ok: list[tuple[str, bool, str]] = []

    # 1. Import rl_config
    try:
        from strategies.rl_config import (  # noqa: F401
            DEFAULT_INTERVAL,
            N_FEATURES,
            PPO_CONFIG,
            RL_CACHE_DIR,
            RL_MODELS_DIR,
            TIMESTEPS_DEFAULT,
            VALIDATION_GATES,
        )

        steps_ok.append(("strategies.rl_config", True, ""))
    except Exception as exc:
        steps_ok.append(("strategies.rl_config", False, str(exc)))

    # 2. Import rl_agent (requires stable-baselines3 + gymnasium)
    try:
        from strategies.rl_agent import RLTradingAgent  # noqa: F401

        steps_ok.append(("strategies.rl_agent", True, ""))
    except Exception as exc:
        steps_ok.append(("strategies.rl_agent", False, str(exc)))

    # 3. Import rl_environment (requires gymnasium + backtest.signals)
    try:
        from strategies.rl_environment import build_env, prepare_dataframe  # noqa: F401

        steps_ok.append(("strategies.rl_environment", True, ""))
    except Exception as exc:
        steps_ok.append(("strategies.rl_environment", False, str(exc)))

    # 4. Import rl_trainer
    try:
        from strategies.rl_trainer import RLTrainer  # noqa: F401

        steps_ok.append(("strategies.rl_trainer", True, ""))
    except Exception as exc:
        steps_ok.append(("strategies.rl_trainer", False, str(exc)))

    # 5. Check stable-baselines3 is available
    try:
        from stable_baselines3 import PPO  # noqa: F401

        steps_ok.append(("stable-baselines3", True, ""))
    except ImportError as exc:
        steps_ok.append(("stable-baselines3", False, str(exc)))

    # 6. Check gymnasium is available
    try:
        import gymnasium as gym  # noqa: F401

        steps_ok.append(("gymnasium", True, ""))
    except ImportError as exc:
        steps_ok.append(("gymnasium", False, str(exc)))

    # 7. Check BacktestDataLoader (data fallback via Polygon → CSV cache)
    try:
        from backtest.data_loader import BacktestDataLoader  # noqa: F401

        steps_ok.append(("BacktestDataLoader", True, ""))
    except ImportError as exc:
        steps_ok.append(("BacktestDataLoader", False, str(exc)))

    # 8. Check memory usage reporting (psutil optional — not a hard requirement)
    try:
        import psutil  # noqa: F401

        steps_ok.append(("psutil (memory reporting)", True, ""))
    except ImportError:
        # psutil is optional — mark as warning, not failure
        steps_ok.append(
            (
                "psutil (memory reporting) [optional]",
                True,
                "not installed — pip install psutil to enable memory stats",
            )
        )

    # 9. Ensure model/cache directories are creatable
    try:
        from strategies.rl_config import RL_CACHE_DIR, RL_MODELS_DIR

        RL_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        RL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        steps_ok.append(("data directories", True, f"models={RL_MODELS_DIR}  cache={RL_CACHE_DIR}"))
    except Exception as exc:
        steps_ok.append(("data directories", False, str(exc)))

    # 10. Validate symbol is known
    try:
        from strategies.rl_config import RL_INSTRUMENT_PARAMS, get_instrument_params

        params = get_instrument_params(symbol)
        known = symbol.upper() in RL_INSTRUMENT_PARAMS
        note = f"STC_OS={params[0]} STC_OB={params[1]} STOP_ATR={params[2]}"
        if not known:
            note = f"(using defaults) {note}"
        steps_ok.append((f"symbol '{symbol}' config", True, note))
    except Exception as exc:
        steps_ok.append((f"symbol '{symbol}' config", False, str(exc)))

    # Print results
    all_ok = True
    for label, ok, note in steps_ok:
        marker = f"{_GREEN}OK{_RESET}" if ok else f"{_RED}FAIL{_RESET}"
        line = f"  [{marker}] {label}"
        if note:
            line += f"  — {note}"
        print(line)
        if not ok:
            all_ok = False

    # Print config summary from successful imports
    print()
    try:
        from strategies.rl_config import (
            N_FEATURES,
            PPO_CONFIG,
            RL_CACHE_DIR,
            RL_MODELS_DIR,
            VALIDATION_GATES,
        )

        print("Configuration:")
        print(f"  Symbol     : {symbol}")
        print(f"  Timesteps  : {timesteps:,}")
        print(f"  Features   : {N_FEATURES}")
        print(f"  Algorithm  : PPO ({PPO_CONFIG['policy']})")
        print(f"  Models dir : {RL_MODELS_DIR}")
        print(f"  Cache dir  : {RL_CACHE_DIR}")
        print()
        print("Validation gates:")
        gates = VALIDATION_GATES
        print(f"  Profit Factor  >= {gates['min_profit_factor']}")
        print(f"  Sharpe Ratio   >= {gates['min_sharpe']}")
        print(f"  Win Rate       >= {gates['min_win_rate']:.0%}")
        print(f"  HOLD Rate      >= {gates['min_hold_rate']:.0%}")
        print(f"  Trade Count    >= {gates['min_trades']}")
        print(f"  Max Drawdown   <= {gates['max_drawdown']:.0%}")
    except Exception:
        pass  # Already reported via steps_ok

    print()
    if all_ok:
        print(f"{_GREEN}{_BOLD}DRY-RUN PASSED — pipeline wired correctly{_RESET}")
        print("Run without --dry-run to begin training.")
        return 0
    else:
        failed = [label for label, ok, _ in steps_ok if not ok]
        print(f"{_RED}{_BOLD}DRY-RUN FAILED — fix the issues above before training{_RESET}")
        print(f"  Failed: {', '.join(failed)}")
        return 1


# ── Memory helper ─────────────────────────────────────────────────────────────


def _mem_mb() -> str:
    """Return current process RSS in MB, or empty string if psutil missing."""
    try:
        import psutil

        proc = psutil.Process(os.getpid())
        rss_mb = proc.memory_info().rss / 1024 / 1024
        return f"{rss_mb:.0f} MB"
    except ImportError:
        return "n/a"


# ── Training progress printer ─────────────────────────────────────────────────


def _print_progress(step: int, ep_info_buffer) -> None:
    """Print a single progress line for the given checkpoint step."""
    import numpy as np

    if ep_info_buffer:
        reward_mean = float(np.mean([ep["r"] for ep in ep_info_buffer]))
        ep_len_mean = float(np.mean([ep["l"] for ep in ep_info_buffer]))
        print(
            f"  [{step:>8,}] reward_mean={reward_mean:+.4f}  "
            f"ep_len_mean={ep_len_mean:.1f}  mem={_mem_mb()}"
        )
    else:
        print(f"  [{step:>8,}] (no episodes completed yet)  mem={_mem_mb()}")


# ── Validation gate printer ───────────────────────────────────────────────────


def _print_validation(metrics: dict, gates: dict, model_path: str) -> None:
    """Print validation gate results table."""
    print("\nValidation Results:")

    def _gate_line(label: str, value, threshold, fmt: str, lower_is_better: bool = False) -> None:
        if lower_is_better:
            passes = value <= threshold
            cmp = f"<= {threshold:{fmt}}"
        else:
            passes = value >= threshold
            cmp = f">= {threshold:{fmt}}"
        formatted = f"{value:{fmt}}"
        # Trim the trailing PASS/FAIL label — rebuild cleanly
        tick = f"{_GREEN}PASS{_RESET}" if passes else f"{_RED}FAIL{_RESET}"
        print(f"  {label:<18} {formatted:>8}  [{tick}]  (gate: {cmp})")

    pf = metrics.get("profit_factor", 0.0)
    sharpe = metrics.get("sharpe", 0.0)
    win_rate = metrics.get("win_rate", 0.0)
    hold_rate = metrics.get("hold_rate", 0.0)
    max_dd = metrics.get("max_drawdown", 1.0)
    n_trades = int(metrics.get("n_trades", 0))

    _gate_line("Profit Factor:", pf, gates["min_profit_factor"], ".2f")
    _gate_line("Sharpe Ratio:", sharpe, gates["min_sharpe"], ".2f")
    _gate_line("Win Rate:", win_rate, gates["min_win_rate"], ".1%")
    _gate_line("HOLD Rate:", hold_rate, gates["min_hold_rate"], ".1%")
    _gate_line("Max Drawdown:", max_dd, gates["max_drawdown"], ".1%", lower_is_better=True)
    _gate_line("Trade Count:", n_trades, gates["min_trades"], "d")

    passes = metrics.get("passes_validation", False)
    print()
    if passes:
        print(f"{_GREEN}{_BOLD}VALIDATION PASSED{_RESET}")
    else:
        print(f"{_RED}{_BOLD}VALIDATION FAILED{_RESET}")
        # Show which gates failed
        failed_gates = []
        if pf < gates["min_profit_factor"]:
            failed_gates.append(f"PF={pf:.2f} (need {gates['min_profit_factor']})")
        if sharpe < gates["min_sharpe"]:
            failed_gates.append(f"Sharpe={sharpe:.2f} (need {gates['min_sharpe']})")
        if win_rate < gates["min_win_rate"]:
            failed_gates.append(f"WR={win_rate:.1%} (need {gates['min_win_rate']:.0%})")
        if hold_rate < gates["min_hold_rate"]:
            failed_gates.append(f"HOLD={hold_rate:.1%} (need {gates['min_hold_rate']:.0%})")
        if max_dd > gates["max_drawdown"]:
            failed_gates.append(f"MaxDD={max_dd:.1%} (limit {gates['max_drawdown']:.0%})")
        if n_trades < gates["min_trades"]:
            failed_gates.append(f"Trades={n_trades} (need {gates['min_trades']})")
        print(f"  Failed gates: {', '.join(failed_gates)}")

    print(f"\nModel saved: {model_path}")


# ── Custom SB3 callback for CLI progress output ───────────────────────────────


def _make_progress_callback(timesteps: int, log_every: int = 10_000):
    """Return a SB3 BaseCallback that prints progress to stdout."""
    try:
        from stable_baselines3.common.callbacks import BaseCallback
    except ImportError:
        return None

    class _CLIProgressCallback(BaseCallback):
        def __init__(self, total_ts: int, log_interval: int):
            super().__init__(verbose=0)
            self._total_ts = total_ts
            self._log_interval = log_interval
            self._last_log = 0

        def _on_step(self) -> bool:
            if self.num_timesteps - self._last_log >= self._log_interval:
                self._last_log = self.num_timesteps
                _print_progress(self.num_timesteps, self.model.ep_info_buffer)
            return True

    return _CLIProgressCallback(timesteps, log_every)


# ── Main training flow ────────────────────────────────────────────────────────


async def run_training(symbol: str, bars: int, timesteps: int) -> int:
    """
    Full training pipeline:
      1. Fetch / load cached data for ``symbol``
      2. Prepare dataframe (compute indicators)
      3. Split into train / test (80/20)
      4. Build environments
      5. Train PPO agent with live CLI progress
      6. Evaluate on OOS test set
      7. Print validation gate results
      8. Save model

    Returns 0 on validation pass, 1 on failure.
    """
    from strategies.rl_agent import RLTradingAgent
    from strategies.rl_config import (
        DEFAULT_INTERVAL,
        MAX_EPISODE_BARS,
        N_FEATURES,
        PPO_CONFIG,
        RL_CACHE_DIR,
        RL_MODELS_DIR,
        TRAIN_LOOKBACK_DAYS,
        VALIDATION_GATES,
    )
    from strategies.rl_environment import build_env, prepare_dataframe
    from strategies.rl_trainer import RLTrainer

    print(f"\n{_BOLD}JARVIS RL Trainer — {symbol}{_RESET}")
    print("=" * 40)
    print(f"Symbol: {symbol} | Bars: {bars:,} | Timesteps: {timesteps:,}")
    print(f"Features: {N_FEATURES} | Algorithm: PPO ({PPO_CONFIG['policy']})")
    print()

    t0 = time.time()

    # 1. Fetch data via BacktestDataLoader (Polygon → CSV cache, standalone — no IBKR required)
    trainer = RLTrainer(data_manager=None)

    print("Fetching data...")
    df_raw = await trainer._fetch_data(
        symbol=symbol,
        interval=DEFAULT_INTERVAL,
        lookback_days=TRAIN_LOOKBACK_DAYS,
    )

    if df_raw is None or len(df_raw) < 100:
        n = len(df_raw) if df_raw is not None else 0
        print(f"{_RED}ERROR: Insufficient data for {symbol} — got {n} bars{_RESET}")
        return 1

    # Clip to requested bar count
    if len(df_raw) > bars:
        df_raw = df_raw.iloc[-bars:].reset_index(drop=True)

    print(f"  {len(df_raw):,} bars fetched for {symbol}")

    # 2. Prepare indicators (uses cache if available)
    print("Computing indicators...")
    cache_path = RL_CACHE_DIR / f"{symbol}_{DEFAULT_INTERVAL}.parquet"
    df = await asyncio.to_thread(
        prepare_dataframe,
        df_raw,
        cache_path=cache_path,
        force_recompute=False,
    )

    if len(df) < 100:
        print(f"{_RED}ERROR: Only {len(df)} valid bars after indicator computation{_RESET}")
        return 1

    print(f"  {len(df):,} bars ready (indicators computed)  mem={_mem_mb()}")

    # 3. Train / test split (80 / 20)
    split_idx = int(len(df) * 0.80)
    df_train = df.iloc[:split_idx].reset_index(drop=True)
    df_test = df.iloc[split_idx:].reset_index(drop=True)
    print(f"  Train: {len(df_train):,} bars | Test: {len(df_test):,} bars")

    # 4. Build environments
    train_env = build_env(
        symbol=symbol,
        df=df_train,
        max_episode_bars=MAX_EPISODE_BARS,
    )
    test_env = build_env(
        symbol=symbol,
        df=df_test,
        max_episode_bars=len(df_test),
    )

    # 5. Train
    print("\nTraining started...")
    log_every = max(10_000, timesteps // 10)
    cli_cb = _make_progress_callback(timesteps, log_interval=log_every)

    agent = RLTradingAgent(symbol=symbol, env=train_env)

    # Patch model.learn to inject our CLI callback alongside the built-in one
    orig_learn = agent.model.learn

    def _patched_learn(total_timesteps, callback=None, **kwargs):
        callbacks = []
        if callback is not None:
            callbacks.append(callback)
        if cli_cb is not None:
            callbacks.append(cli_cb)
        from stable_baselines3.common.callbacks import CallbackList

        combined = (
            CallbackList(callbacks) if len(callbacks) > 1 else (callbacks[0] if callbacks else None)
        )
        return orig_learn(total_timesteps=total_timesteps, callback=combined, **kwargs)

    agent.model.learn = _patched_learn  # type: ignore[method-assign]

    train_start = time.time()
    training_summary = await asyncio.to_thread(agent.train, timesteps)
    train_elapsed = time.time() - train_start

    print(f"\nTraining complete in {train_elapsed:.1f}s  mem={_mem_mb()}")

    # Print action distribution from training
    dist = training_summary.get("action_distribution", {})
    if dist:
        dist_str = "  ".join(f"{k}={v:.1%}" for k, v in dist.items())
        print(f"Action distribution: {dist_str}")

    # 6. Evaluate OOS
    print("\nEvaluating on OOS test set...")
    metrics = await asyncio.to_thread(agent.evaluate, test_env, n_episodes=1)

    # 7. Save model
    RL_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = await asyncio.to_thread(agent.save)
    model_path_display = f"{model_path}.zip"

    # 8. Print results
    _print_validation(metrics, VALIDATION_GATES, model_path_display)

    total_elapsed = time.time() - t0
    print(f"\nTotal wall time: {total_elapsed:.1f}s")

    return 0 if metrics.get("passes_validation", False) else 1


# ── Entry point ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbol = args.symbol.upper()

    if args.dry_run:
        return run_dry_run(symbol=symbol, timesteps=args.timesteps)

    return asyncio.run(
        run_training(
            symbol=symbol,
            bars=args.bars,
            timesteps=args.timesteps,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
