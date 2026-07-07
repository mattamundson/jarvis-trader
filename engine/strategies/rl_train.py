"""
JARVIS TRADER — PPO Training Entry Points
==========================================

Synchronous training utilities for the RL strategy discovery pipeline.
This module provides the two primary public functions:

    train_ppo(symbol, n_steps, save_path) -> dict
        Train a PPO agent on historical data for the given symbol.
        Returns training metrics; saves the policy zip to save_path.

    policy_to_hypothesis(policy_path, symbol) -> StrategyHypothesis
        Convert a saved PPO policy into a StrategyHypothesis that can be
        fed to gate v2, just like ResearchAgent output.

Both functions are training-time only.  They do not route live orders,
do not touch engine/risk/, and are gated behind ENABLE_RL_STRATEGY_DISCOVERY.

Lazy imports:
    stable-baselines3 (PPO, etc.) is imported inside functions so this
    module can be imported cleanly even when SB3 is not installed.  The
    engine boot path imports strategies.rl_train at module level for the
    health endpoint — a missing SB3 install must never crash the engine.

Feature-flag guard:
    is_rl_discovery_enabled() checks ENABLE_RL_STRATEGY_DISCOVERY env var.
    All public functions check this and raise RuntimeError when disabled.
    Override for testing: os.environ["ENABLE_RL_STRATEGY_DISCOVERY"] = "1".
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Feature flag ──────────────────────────────────────────────────────────────


def is_rl_discovery_enabled() -> bool:
    """Return True only when ENABLE_RL_STRATEGY_DISCOVERY is set to '1'."""
    return os.environ.get("ENABLE_RL_STRATEGY_DISCOVERY", "0").strip() == "1"


# ── Output paths ──────────────────────────────────────────────────────────────

_ENGINE_ROOT = Path(__file__).resolve().parent.parent
RL_POLICIES_DIR = _ENGINE_ROOT / "data" / "rl_policies"
RESEARCH_HYPOTHESES_DIR = _ENGINE_ROOT / "data" / "research_hypotheses"


# ── StrategyHypothesis import (lazy, avoids circular import at module level) ──


def _get_hypothesis_class():
    """Return the StrategyHypothesis Pydantic model class (lazy import)."""
    from agents.research_agent import StrategyHypothesis  # noqa: PLC0415

    return StrategyHypothesis


# ── Synthetic data for quick-smoke / testing ──────────────────────────────────


def _make_synthetic_df(n_bars: int = 300, symbol: str = "MES") -> pd.DataFrame:
    """
    Build a minimal synthetic OHLCV + indicators DataFrame for smoke tests.

    This is the same factory used in test_rl_module.py — kept here so the
    smoke runner can also use it without importing test utilities.
    """
    rng = np.random.default_rng(seed=42)

    base = 5000.0 if symbol.upper() in ("MES", "MNQ") else 75.0
    close = base + np.cumsum(rng.normal(0, 5, n_bars))
    high = close + rng.uniform(2, 10, n_bars)
    low = close - rng.uniform(2, 10, n_bars)
    open_ = close + rng.normal(0, 3, n_bars)
    volume = rng.integers(1000, 10000, n_bars).astype(float)
    atr = rng.uniform(8, 20, n_bars)

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "atr": atr,
            "stc_val": rng.uniform(10, 90, n_bars),
            "ema_21": close * rng.uniform(0.99, 1.01, n_bars),
            "ema_trend": rng.choice(["bullish", "neutral", "bearish"], n_bars),
            "phase_val": rng.uniform(-50, 50, n_bars),
            "volume_signal": rng.choice(["buyer_dominant", "balanced", "seller_dominant"], n_bars),
            "cci_50": rng.uniform(-150, 150, n_bars),
            "buy_pct": rng.uniform(20, 80, n_bars),
            "macd_hist": rng.normal(0, 1, n_bars),
            "rsi": rng.uniform(30, 70, n_bars),
            "bb_upper": close + atr * 2,
            "bb_lower": close - atr * 2,
            "adx": rng.uniform(15, 45, n_bars),
        }
    )


# ── Public API ────────────────────────────────────────────────────────────────


def train_ppo(
    symbol: str,
    n_steps: int = 10_000,
    save_path: Optional[str] = None,
    df: Optional[pd.DataFrame] = None,
    quick_smoke: bool = False,
    _bypass_flag: bool = False,
) -> dict:
    """
    Train a PPO agent on historical data for the given symbol.

    Parameters
    ----------
    symbol      : Futures symbol, e.g. 'MES', 'MNQ', 'MCL'.
    n_steps     : Total training timesteps (ignored when quick_smoke=True,
                  which runs 100 steps only).
    save_path   : Directory to save the policy zip.  Defaults to
                  engine/data/rl_policies/<symbol>-<timestamp>.zip.
    df          : Optional pre-built OHLCV + indicators DataFrame.  When
                  None and quick_smoke=True, a synthetic DataFrame is used.
                  When None and quick_smoke=False, the BacktestDataLoader
                  is called to fetch real historical data.
    quick_smoke : When True, runs only 100 timesteps on synthetic data —
                  CPU-friendly, completes in ~10 seconds, validates the
                  full pipeline without real data or GPU.
    _bypass_flag: Internal flag used by tests to skip the feature-flag
                  check.  Do not set from production code.

    Returns
    -------
    dict with keys:
        symbol          : str
        n_steps         : int (actual steps trained)
        mean_reward     : float (mean episode reward over training)
        episode_rewards : list[float] (reward history from callback)
        training_time_s : float (wall-clock seconds)
        policy_path     : str (absolute path to saved .zip)
        quick_smoke     : bool
        status          : 'ok' | 'error'

    Raises
    ------
    RuntimeError if ENABLE_RL_STRATEGY_DISCOVERY != '1' and _bypass_flag=False.
    ImportError  if stable-baselines3 is not installed.
    """
    if not _bypass_flag and not is_rl_discovery_enabled():
        raise RuntimeError(
            "RL strategy discovery is disabled.  " "Set ENABLE_RL_STRATEGY_DISCOVERY=1 to enable."
        )

    # Lazy import so engine boot never fails due to missing SB3
    try:
        from stable_baselines3 import PPO  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "stable-baselines3 is required for RL training.  "
            "Install it: pip install stable-baselines3"
        ) from exc

    actual_steps = 100 if quick_smoke else n_steps

    # ── Build / fetch DataFrame ───────────────────────────────────────────
    if df is None:
        if quick_smoke:
            logger.info("[rl_train] quick_smoke=True — using synthetic data (300 bars)")
            df = _make_synthetic_df(n_bars=300, symbol=symbol)
        else:
            df = _fetch_real_data(symbol)

    if len(df) < 60:
        raise ValueError(f"DataFrame too small for training ({len(df)} bars); need >= 60.")

    # ── Build environment ─────────────────────────────────────────────────
    from strategies.rl_config import PPO_CONFIG  # noqa: PLC0415
    from strategies.rl_env import make_trading_env  # noqa: PLC0415

    env = make_trading_env(df=df, symbol=symbol)

    # ── Instantiate PPO ───────────────────────────────────────────────────
    model = PPO(
        policy=PPO_CONFIG["policy"],
        env=env,
        learning_rate=PPO_CONFIG["learning_rate"],
        n_steps=min(PPO_CONFIG["n_steps"], actual_steps),
        batch_size=min(PPO_CONFIG["batch_size"], actual_steps),
        n_epochs=PPO_CONFIG["n_epochs"],
        gamma=PPO_CONFIG["gamma"],
        gae_lambda=PPO_CONFIG["gae_lambda"],
        clip_range=PPO_CONFIG["clip_range"],
        ent_coef=PPO_CONFIG["ent_coef"],
        vf_coef=PPO_CONFIG["vf_coef"],
        max_grad_norm=PPO_CONFIG["max_grad_norm"],
        verbose=0,
    )

    # ── Train ─────────────────────────────────────────────────────────────
    from strategies.rl_agent import TrainingProgressCallback  # noqa: PLC0415

    callback = TrainingProgressCallback(log_interval=max(50, actual_steps // 20))

    t_start = time.monotonic()
    model.learn(
        total_timesteps=actual_steps,
        callback=callback,
        reset_num_timesteps=True,
        progress_bar=False,
    )
    elapsed = time.monotonic() - t_start

    # ── Collect metrics ───────────────────────────────────────────────────
    cb_summary = callback.get_summary()
    episode_rewards: list[float] = cb_summary.get("episode_rewards", [])
    mean_reward = float(np.mean(episode_rewards)) if episode_rewards else 0.0

    # ── Save policy ───────────────────────────────────────────────────────
    RL_POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if save_path:
        policy_stem = Path(save_path) / f"{symbol.upper()}-{timestamp}"
    else:
        policy_stem = RL_POLICIES_DIR / f"{symbol.upper()}-{timestamp}"

    model.save(str(policy_stem))
    zip_path = str(policy_stem) + ".zip"

    logger.info(
        "[rl_train] Training complete | symbol=%s steps=%d time=%.1fs "
        "mean_reward=%.4f policy=%s",
        symbol,
        actual_steps,
        elapsed,
        mean_reward,
        zip_path,
    )

    return {
        "symbol": symbol,
        "n_steps": actual_steps,
        "mean_reward": round(mean_reward, 4),
        "episode_rewards": episode_rewards[-20:],
        "action_distribution": cb_summary.get("action_distribution", {}),
        "training_time_s": round(elapsed, 2),
        "policy_path": zip_path,
        "quick_smoke": quick_smoke,
        "status": "ok",
    }


def policy_to_hypothesis(
    policy_path: str,
    symbol: str,
    timeframe: str = "1h",
    _bypass_flag: bool = False,
) -> object:
    """
    Convert a saved PPO policy into a StrategyHypothesis.

    The returned hypothesis can be fed directly to gate v2 alongside
    ResearchAgent hypotheses — the schema is identical.

    Signal weights are derived from the PPO policy's action distribution
    observed during a short evaluation rollout (100 steps on synthetic data).
    Where the policy shows strong directional bias (high BUY or SELL rate),
    that is encoded as a signal weight. Otherwise, weights default to
    neutral HOLD-dominant values.

    Parameters
    ----------
    policy_path : Absolute path to the saved .zip file (with or without .zip).
    symbol      : Futures symbol, e.g. 'MES'.
    timeframe   : Bar timeframe the policy was trained on (default: '1h').
    _bypass_flag: Internal flag for tests to skip the feature-flag check.

    Returns
    -------
    StrategyHypothesis (Pydantic model) ready for gate v2 scoring.

    Raises
    ------
    RuntimeError if ENABLE_RL_STRATEGY_DISCOVERY != '1' and _bypass_flag=False.
    FileNotFoundError if the policy zip is not found.
    ImportError if stable-baselines3 is not installed.
    """
    if not _bypass_flag and not is_rl_discovery_enabled():
        raise RuntimeError(
            "RL strategy discovery is disabled.  " "Set ENABLE_RL_STRATEGY_DISCOVERY=1 to enable."
        )

    try:
        from stable_baselines3 import PPO  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("stable-baselines3 is required.  pip install stable-baselines3") from exc

    zip_path = policy_path if policy_path.endswith(".zip") else policy_path + ".zip"
    if not Path(zip_path).exists():
        raise FileNotFoundError(f"Policy not found: {zip_path}")

    # ── Build env for rollout ─────────────────────────────────────────────
    df = _make_synthetic_df(n_bars=200, symbol=symbol)
    from strategies.rl_env import make_trading_env  # noqa: PLC0415

    env = make_trading_env(df=df, symbol=symbol)

    # ── Load policy ───────────────────────────────────────────────────────
    model = PPO.load(zip_path, env=env)

    # ── Short rollout to observe action distribution ───────────────────────
    action_counts = {"HOLD": 0, "BUY": 0, "SELL": 0, "CLOSE": 0}
    action_names = {0: "HOLD", 1: "BUY", 2: "SELL", 3: "CLOSE"}

    obs, _ = env.reset(seed=0)
    for _ in range(100):
        action, _ = model.predict(np.array(obs, dtype=np.float32), deterministic=True)
        action_int = int(action)
        action_counts[action_names.get(action_int, "HOLD")] += 1
        obs, _, terminated, truncated, _ = env.step(action_int)
        if terminated or truncated:
            obs, _ = env.reset()

    total = sum(action_counts.values()) or 1
    buy_rate = action_counts["BUY"] / total
    sell_rate = action_counts["SELL"] / total
    hold_rate = action_counts["HOLD"] / total

    # ── Derive signal weights from action distribution ────────────────────
    # A policy that buys a lot weighs long signals highly.
    # A policy that shorts a lot weighs short-side signals.
    # A patient policy (high HOLD) weighs regime filtering heavily.
    signal_weights: dict[str, float] = {}
    if buy_rate > 0.30:
        signal_weights["stc_crossover"] = round(buy_rate, 3)
        signal_weights["regime_bull"] = round(min(buy_rate * 1.2, 1.0), 3)
    if sell_rate > 0.30:
        signal_weights["stc_ob_level"] = round(sell_rate, 3)
        signal_weights["regime_bear"] = round(min(sell_rate * 1.2, 1.0), 3)
    if hold_rate > 0.50:
        signal_weights["vwap_proximity"] = round(hold_rate * 0.5, 3)
    if not signal_weights:
        # Default to STC-dominated ensemble when distribution is ambiguous
        signal_weights = {
            "stc_crossover": 0.40,
            "vwap_proximity": 0.30,
            "atr_breakout": 0.30,
        }

    # ── Derive risk params from instrument config ─────────────────────────
    from strategies.rl_config import get_instrument_params  # noqa: PLC0415

    params = get_instrument_params(symbol)
    stc_os, stc_ob, stop_atr, t1_atr = params[0], params[1], params[2], params[3]
    risk_params = {
        "stop_atr_mult": float(stop_atr),
        "tp_atr_mult": float(t1_atr),
    }

    # ── Build entry / exit rules from action bias ─────────────────────────
    if buy_rate >= sell_rate:
        entry_rules = [
            f"PPO policy bias: long ({buy_rate:.1%} BUY vs {sell_rate:.1%} SELL "
            f"over 100-step eval rollout)",
            f"STC oscillator below {stc_ob} (not overbought)",
            "Regime filter: TRENDING_BULL or RANGE_BOUND",
        ]
        exit_rules = [
            f"Take-profit at entry + {t1_atr:.2f} * ATR",
            f"Stop-loss at entry - {stop_atr:.2f} * ATR",
            "CLOSE action from RL policy when position is deteriorating",
        ]
    else:
        entry_rules = [
            f"PPO policy bias: short ({sell_rate:.1%} SELL vs {buy_rate:.1%} BUY "
            f"over 100-step eval rollout)",
            f"STC oscillator above {stc_os} (not oversold)",
            "Regime filter: TRENDING_BEAR",
        ]
        exit_rules = [
            f"Take-profit at entry - {t1_atr:.2f} * ATR (short side)",
            f"Stop-loss at entry + {stop_atr:.2f} * ATR (short side)",
            "CLOSE action from RL policy when position is deteriorating",
        ]

    # ── Load metadata if present ─────────────────────────────────────────
    meta_path = zip_path.replace(".zip", ".json")
    meta_summary = ""
    if Path(meta_path).exists():
        try:
            with open(meta_path) as fh:
                meta = json.load(fh)
            ts = meta.get("timesteps", "?")
            meta_summary = f"  Trained for {ts:,} timesteps.".replace("?,", "?")
        except Exception:
            pass

    policy_stem = Path(zip_path).stem
    slug = f"rl-{symbol.lower()}-{policy_stem[:12]}"

    rationale = (
        f"RL-discovered policy via PPO training on {timeframe} {symbol} bars.{meta_summary} "
        f"Action distribution over 100-step eval: "
        f"HOLD={hold_rate:.1%} BUY={buy_rate:.1%} SELL={sell_rate:.1%} "
        f"CLOSE={action_counts['CLOSE'] / total:.1%}.  "
        f"Signal weights derived from action distribution; risk params from "
        f"rl_config.RL_INSTRUMENT_PARAMS['{symbol}'].  "
        f"Gate v2 re-evaluates confidence after backtest — confidence set to 0.0."
    )

    StrategyHypothesis = _get_hypothesis_class()
    hypothesis = StrategyHypothesis(
        name=slug,
        symbol=symbol.upper(),
        timeframe=timeframe,
        entry_rules=entry_rules,
        exit_rules=exit_rules,
        signal_weights=signal_weights,
        risk_params=risk_params,
        rationale=rationale,
        confidence=0.0,  # gate v2 evaluates after backtest
    )

    logger.info(
        "[rl_train] policy_to_hypothesis | symbol=%s slug=%s " "buy=%.1f%% sell=%.1f%% hold=%.1f%%",
        symbol,
        slug,
        buy_rate * 100,
        sell_rate * 100,
        hold_rate * 100,
    )
    return hypothesis


# ── Internal: real data fetch ─────────────────────────────────────────────────


def _fetch_real_data(symbol: str, lookback_days: int = 365) -> pd.DataFrame:
    """
    Fetch historical OHLCV + indicators via BacktestDataLoader.

    Used by train_ppo() when quick_smoke=False and no df is provided.
    Falls back gracefully if the loader fails.
    """
    try:
        from datetime import timedelta  # noqa: PLC0415

        from backtest.data_loader import BacktestDataLoader  # noqa: PLC0415
        from backtest.signals import compute_all_indicators  # noqa: PLC0415

        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        loader = BacktestDataLoader()
        df_raw = loader.load(symbol, start_date, end_date, "1h")

        if df_raw is None or df_raw.empty:
            raise ValueError(f"BacktestDataLoader returned empty DataFrame for {symbol}")

        df_raw = df_raw.rename(
            columns={
                c: c.lower()
                for c in df_raw.columns
                if c.lower() in ("open", "high", "low", "close", "volume")
            }
        )
        df_proc = compute_all_indicators(df_raw)
        return df_proc.dropna(subset=["atr", "stc_val"]).reset_index(drop=True)

    except Exception as exc:
        logger.error("[rl_train] _fetch_real_data failed (%s) — aborting", exc)
        raise
